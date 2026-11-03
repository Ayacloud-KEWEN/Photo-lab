# LUMEN Studio — Project Specification

## 1. Product Overview

Build a Windows desktop application named LUMEN Studio.

LUMEN Studio is a local-first personal photography and video asset management workstation with integrated AI capabilities.

Its primary purpose is to help photography enthusiasts organize, browse, search, analyze, edit, and preserve large personal collections of RAW photographs, JPEG/HEIC images, and MP4/MOV videos.

The application should combine the usability of a modern photo library, the metadata capabilities of professional photography software, and the intelligence of AI-assisted visual search.

UI Language: Chinese first, then support English and French

## 2. Product Principles

- Local-first: original media files remain on the user's local drives.
- Non-destructive: never modify original media files.
- AI-assisted: AI should reduce manual organization work.
- Privacy-conscious: cloud AI requires explicit user consent.
- Professional but simple: prioritize usability over excessive features.
- Modular: every major subsystem should be independently maintainable.
- Reliable: protect user data and support recovery from interrupted operations.

## 3. Target Platform

- Windows 10/11, prioritizing Windows 11.
- Desktop application using Tauri 2.
- React and TypeScript frontend.
- Python backend for media processing and AI.
- SQLite database.
- Local filesystem storage.

## 4. Technology Stack

Frontend:
- Tauri 2
- React
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui

Backend:
- Python
- FastAPI for local API communication
- Pydantic for data validation
- SQLite
- Background task processing

Media:
- ExifTool
- LibRaw / rawpy
- Pillow
- OpenCV
- FFmpeg / FFprobe

AI:
- SigLIP or OpenCLIP for image embeddings
- A locally executable vision-language model
- Vector similarity search
- Pluggable cloud multimodal AI providers

## 5. Core Modules

1. Library: photo and video management.
2. Viewer: full-resolution image and video viewing.
3. Explore: timeline, map and metadata-based discovery.
4. AI Search: semantic image search.
5. AI Assistant: image descriptions, analysis and recommendations.
6. Develop: non-destructive photo editing.
7. Projects: collections and travel photography projects.
8. System: storage, indexing, AI models and backups.

## 6. Database Architecture

Create modular SQLite database tables:

- media_assets
- media_files
- media_metadata
- media_locations
- tags
- media_tags
- collections
- collection_items
- ai_analysis
- embeddings
- edit_history
- tasks
- storage_roots
- app_settings

Separate logical media assets from physical files.

Support RAW+JPEG pairing, multiple file locations, external drive disconnection, file relocation and duplicate detection.

Use database migrations. Do not modify production database schemas manually.

## 7. Media Processing

Implement an asynchronous media ingestion pipeline:

1. Scan configured directories.
2. Detect supported media formats.
3. Extract metadata.
4. Calculate file fingerprints.
5. Register assets and files.
6. Generate thumbnails.
7. Generate preview images.
8. Extract video metadata and preview frames.
9. Schedule optional AI analysis.

Importing must not wait for AI analysis.

Tasks must support progress reporting, retries, cancellation and recovery after application restart.

## 8. AI Architecture

Local AI:
- Image embeddings.
- Image-text semantic search.
- Automatic scene classification.
- Similar-image retrieval.
- Optional image quality assessment.

Cloud AI:
- Detailed image descriptions.
- Photography critique.
- Composition and lighting analysis.
- Group photo selection.
- Travel story generation.

Cloud AI must be opt-in. Show the user which images are being uploaded. Store API credentials securely.

Cache analysis results using file fingerprints and model versions.

## 9. MVP Scope

The first release must support:

- Directory scanning.
- RAW, JPEG, HEIC, MP4 and MOV indexing.
- EXIF extraction.
- Thumbnail generation.
- Photo grid and full-screen viewer.
- Video playback.
- Timeline browsing.
- Metadata filtering.
- Favorites and ratings.
- Tags and notes.
- Basic text search.
- Duplicate detection.
- Local AI image tagging.
- Semantic image search.
- Database backup and restoration.

Do not implement advanced RAW editing, multitrack video editing, or complex cloud synchronization in MVP.

## 10. UI/UX Guidelines

Design a restrained, premium photography application.

Visual direction:
- Dark theme by default.
- Neutral charcoal backgrounds.
- Minimal decoration.
- Photography-centered layouts.
- Professional typography.
- Efficient keyboard navigation.
- Responsive thumbnail grid.
- Persistent but unobtrusive AI assistant panel.

Avoid excessive gradients, decorative cards and unnecessary animations.

## 11. Development Rules

- Work in small, independently testable increments.
- Do not generate the entire application in one step.
- Define interfaces before implementing major modules.
- Keep frontend, backend, media engine and AI engine separated.
- Use type-safe API contracts.
- Add tests for every critical data operation.
- Never overwrite original media files.
- Never delete user media automatically.
- Use structured logging and error reporting.
- Document important architectural decisions.
- Maintain a README and PROJECT_SPEC.md.
- Ask before making architectural changes that affect existing modules.

## 12. First Assignment

Do not start implementing all features immediately.

First produce:

1. A detailed system architecture.
2. A proposed project directory structure.
3. An initial database schema.
4. API endpoint specifications.
5. A development milestone plan.
6. A list of technical risks and dependencies.
7. A minimal working prototype plan.

Then wait for approval before proceeding to implementation.

The first prototype should demonstrate:
- Windows desktop application startup.
- SQLite database initialization.
- Selection of a local photo directory.
- Scanning JPEG files.
- Displaying generated thumbnails in a gallery.

The prototype must be runnable and testable before expanding its scope.