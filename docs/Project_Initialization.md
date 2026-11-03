# LUMEN Studio — Phase 1: Project Initialization

You are acting as a senior Windows desktop application engineer.

Read and follow the existing PROJECT_SPEC.md carefully.

Your task is to initialize the LUMEN Studio application and deliver a working desktop prototype.

## 1. Objectives

Create a runnable Windows desktop application using:

- Tauri 2
- React
- TypeScript
- Vite
- Tailwind CSS
- Python
- FastAPI
- SQLite

The application must have a clean separation between frontend, desktop runtime, backend services and database.
UI Language: Chinese first, then support English and French

## 2. Initial Application Interface

Build a professional photography application interface with:

- Dark theme by default.
- Left navigation sidebar.
- Main content area.
- Top search bar.
- Bottom status bar.
- Right-side inspector panel, initially collapsible.

Navigation items:

- Library
- Timeline
- Map
- AI Search
- Collections
- Settings

The initial Library page should display an empty-state screen with a button to select a local photo directory.

Use a restrained, premium photography software aesthetic. Avoid excessive decoration.

## 3. Backend Initialization

Create a Python backend using FastAPI.

Implement:

- Application startup and shutdown.
- SQLite database initialization.
- Database migration mechanism.
- Health check endpoint.
- Configuration management.
- Structured logging.

The backend should run locally and communicate with the Tauri frontend.

## 4. Initial Database

Create the initial tables:

- media_assets
- media_files
- media_metadata
- storage_roots
- tasks
- app_settings

Use proper primary keys, foreign keys, indexes and database transactions.

Do not create unnecessary tables yet.

## 5. Local Directory Selection

Implement a Windows native directory selection dialog.

When a user selects a directory:

1. Register it as a storage root.
2. Save its root path.
3. Display the selected directory in the application.
4. Prepare the directory for future media scanning.

Do not move, rename or modify any original files.

## 6. API Design

Create versioned API endpoints:

- GET /api/v1/health
- GET /api/v1/storage-roots
- POST /api/v1/storage-roots
- DELETE /api/v1/storage-roots/{id}

Validate requests and responses using Pydantic models.

## 7. Development Quality

Requirements:

- Use TypeScript strict mode.
- Use Python type hints.
- Separate business logic from API routes.
- Add basic unit tests.
- Add error handling.
- Document installation and development commands.
- Do not hardcode machine-specific paths.
- Do not expose backend ports unnecessarily.

## 8. Deliverables

Before finishing, provide:

1. Complete project directory structure.
2. Working frontend.
3. Working Python backend.
4. SQLite initialization and migrations.
5. Functional directory selection.
6. README with Windows setup instructions.
7. Tests and test results.

## 9. Development Workflow

Work incrementally.

First inspect the environment and propose the implementation plan.

Then initialize the project.

After implementation, run the application and verify that all essential functions work.

Do not proceed to media scanning or AI integration in this phase.

Do not silently change the architecture defined in PROJECT_SPEC.md.

If a technical dependency or architectural decision needs to change, explain the reason and ask for approval.