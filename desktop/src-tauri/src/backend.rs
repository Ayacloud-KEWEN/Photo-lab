//! Lifecycle of the Python backend process (see docs/ARCHITECTURE.md, ADR-001).
//!
//! 1. Spawn `python -m lumen --watch-stdin` (dev) or the bundled `lumen-backend.exe`
//!    with a fresh token, the data directory and the allowed CORS origins.
//! 2. Wait for the `{"event": "ready", "port": N}` handshake line on stdout.
//! 3. On exit, close stdin so the backend shuts down gracefully; kill it if it doesn't.

use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

const DATA_DIR_NAME: &str = "LUMEN Studio";
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(5);

/// Reported to the frontend through the `backend_status` command.
#[derive(Clone, Debug, Serialize)]
#[serde(
    tag = "state",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
pub enum BackendStatus {
    Starting,
    Ready { base_url: String, token: String },
    Failed { message: String },
}

#[derive(Deserialize)]
#[serde(tag = "event", rename_all = "lowercase")]
enum Handshake {
    Ready { port: u16 },
    Failed { message: String },
}

struct Inner {
    status: BackendStatus,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    shutting_down: bool,
    #[cfg(windows)]
    job: Option<crate::job::Job>,
}

#[derive(Clone)]
pub struct Backend {
    inner: Arc<Mutex<Inner>>,
}

impl Default for Backend {
    fn default() -> Self {
        Self {
            inner: Arc::new(Mutex::new(Inner {
                status: BackendStatus::Starting,
                child: None,
                stdin: None,
                shutting_down: false,
                #[cfg(windows)]
                job: None,
            })),
        }
    }
}

impl Backend {
    pub fn status(&self) -> BackendStatus {
        self.lock().status.clone()
    }

    pub fn start(&self, app: &AppHandle) {
        if let Err(message) = self.try_start(app) {
            eprintln!("[lumen] backend failed to start: {message}");
            self.lock().status = BackendStatus::Failed { message };
        }
    }

    fn try_start(&self, app: &AppHandle) -> Result<(), String> {
        let data_dir = app
            .path()
            .local_data_dir()
            .map_err(|e| format!("Cannot resolve local data directory: {e}"))?
            .join(DATA_DIR_NAME);
        let token = format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        );

        let mut command = backend_command()?;
        command
            .arg("--watch-stdin")
            .env("LUMEN_TOKEN", &token)
            .env("LUMEN_DATA_DIR", &data_dir)
            .env("LUMEN_HOST", "127.0.0.1")
            .env("LUMEN_PORT", "0")
            .env("LUMEN_ALLOWED_ORIGINS", allowed_origins())
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = command
            .spawn()
            .map_err(|e| format!("Cannot launch backend process: {e}"))?;

        #[cfg(windows)]
        let job = match crate::job::Job::kill_on_close()
            .and_then(|job| job.assign(&child).map(|_| job))
        {
            Ok(job) => Some(job),
            Err(e) => {
                eprintln!("[lumen] could not attach backend to a job object: {e}");
                None
            }
        };

        let stdout = child.stdout.take().expect("stdout is piped");
        let stderr = child.stderr.take().expect("stderr is piped");
        let stdin = child.stdin.take();

        {
            let mut inner = self.lock();
            inner.child = Some(child);
            inner.stdin = stdin;
            #[cfg(windows)]
            {
                inner.job = job;
            }
        }

        let backend = self.clone();
        thread::Builder::new()
            .name("backend-stdout".into())
            .spawn(move || backend.read_handshake(stdout, token))
            .map_err(|e| e.to_string())?;
        thread::Builder::new()
            .name("backend-stderr".into())
            .spawn(move || forward_logs(stderr))
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    fn read_handshake(&self, stdout: impl Read, token: String) {
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            match serde_json::from_str::<Handshake>(&line) {
                Ok(Handshake::Ready { port }) => {
                    eprintln!("[lumen] backend ready on 127.0.0.1:{port}");
                    self.lock().status = BackendStatus::Ready {
                        base_url: format!("http://127.0.0.1:{port}"),
                        token: token.clone(),
                    };
                }
                Ok(Handshake::Failed { message }) => {
                    self.lock().status = BackendStatus::Failed { message };
                }
                Err(_) => eprintln!("[backend:stdout] {line}"),
            }
        }

        // stdout closed: the process has exited.
        let mut inner = self.lock();
        if !inner.shutting_down && !matches!(inner.status, BackendStatus::Failed { .. }) {
            inner.status = BackendStatus::Failed {
                message: "Backend process exited unexpectedly".into(),
            };
        }
    }

    /// Ask the backend to stop (by closing its stdin), then kill it after a timeout.
    pub fn shutdown(&self) {
        let child = {
            let mut inner = self.lock();
            if inner.shutting_down {
                return;
            }
            inner.shutting_down = true;
            inner.stdin.take(); // dropping closes the pipe
            inner.child.take()
        };

        if let Some(mut child) = child {
            let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
            loop {
                match child.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) if Instant::now() < deadline => {
                        thread::sleep(Duration::from_millis(50))
                    }
                    _ => {
                        eprintln!("[lumen] backend did not stop in time, killing it");
                        let _ = child.kill();
                        let _ = child.wait();
                        break;
                    }
                }
            }
        }

        #[cfg(windows)]
        {
            // Closing the job kills anything still left in it.
            self.lock().job.take();
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }
}

fn forward_logs(stderr: impl Read) {
    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
        eprintln!("[backend] {line}");
    }
}

fn allowed_origins() -> &'static str {
    if cfg!(debug_assertions) {
        "http://tauri.localhost,https://tauri.localhost,tauri://localhost,http://localhost:1420"
    } else {
        "http://tauri.localhost,https://tauri.localhost,tauri://localhost"
    }
}

/// How to launch the backend.
///
/// - `LUMEN_BACKEND_PYTHON` set: `<that python> -m lumen` (any build).
/// - Debug builds: the repository's `backend/.venv` interpreter.
/// - Release builds: `lumen-backend.exe` bundled next to the app executable.
fn backend_command() -> Result<Command, String> {
    if let Some(python) = std::env::var_os("LUMEN_BACKEND_PYTHON") {
        let mut command = Command::new(python);
        command.args(["-m", "lumen"]);
        return Ok(command);
    }

    #[cfg(debug_assertions)]
    {
        let backend_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("backend");
        let python = if cfg!(windows) {
            backend_dir.join(".venv").join("Scripts").join("python.exe")
        } else {
            backend_dir.join(".venv").join("bin").join("python")
        };
        if !python.exists() {
            return Err(format!(
                "Python virtual environment not found at {}. Run scripts\\setup.ps1 first.",
                python.display()
            ));
        }
        let mut command = Command::new(python);
        command.args(["-m", "lumen"]).current_dir(backend_dir);
        Ok(command)
    }

    #[cfg(not(debug_assertions))]
    {
        let exe_dir = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .map(PathBuf::from)
            .ok_or("Cannot resolve application directory")?;
        let sidecar = exe_dir.join(if cfg!(windows) {
            "lumen-backend.exe"
        } else {
            "lumen-backend"
        });
        if !sidecar.exists() {
            return Err(format!(
                "Bundled backend not found at {}",
                sidecar.display()
            ));
        }
        Ok(Command::new(sidecar))
    }
}
