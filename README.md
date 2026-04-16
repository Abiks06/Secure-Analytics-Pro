# Secure Analytics Pro - Monorepo

This is a unified repository for the **Secure Analytics Pro** project, consisting of a FastAPI backend and a React frontend.

## Project Architecture

- **Backend/**: Python FastAPI service. Handles data processing (Pandas), authentication (Supabase), and security validation.
- **Frontend/**: React application built with Vite and Tailwind CSS.
- **Root**: Monorepo configurations and scripts to manage both services.

## Getting Started

### Prerequisites

- Node.js & npm
- Python 3.8+
- [Git](https://git-scm.com/)

### Setup

1. **Clone the repository** (if not already local):
   ```bash
   git clone <repository-url>
   cd secure-analytics-pro
   ```

2. **Backend Setup**:
   - Ensure you have a virtual environment in `Backend/venv`.
   - Install dependencies:
     ```bash
     cd Backend
     pip install -r requirements.txt
     ```

3. **Frontend Setup**:
   - Install dependencies:
     ```bash
     cd Frontend
     npm install
     ```

### Development

To run both the frontend and backend concurrently from the root:

```bash
npm run dev
```

Individual commands:
- `npm run dev:frontend`: Run only the React app.
- `npm run dev:backend`: Run only the FastAPI server.

## Workspace Management

Open the `secure-analytics-pro.code-workspace` file in VS Code to see the Frontend, Backend, and Root as separate logical folders in your sidebar.

## Production Pushing Steps

1. Create a new repository on GitHub.
2. Link your local repo:
   ```bash
   git remote add origin <your-github-url>
   git branch -M main
   git add .
   git commit -m "chore: initial monorepo setup"
   git push -u origin main
   ```
