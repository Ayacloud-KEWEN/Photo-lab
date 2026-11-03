mod backend;
#[cfg(windows)]
mod job;

use backend::{Backend, BackendStatus};
use tauri::{Manager, RunEvent};

/// Polled by the frontend until the backend is ready (or has failed).
#[tauri::command]
fn backend_status(backend: tauri::State<'_, Backend>) -> BackendStatus {
    backend.status()
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Backend::default())
        .setup(|app| {
            app.state::<Backend>().start(app.handle());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_status])
        .build(tauri::generate_context!())
        .expect("failed to build LUMEN Studio");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Backend>().shutdown();
        }
    });
}
