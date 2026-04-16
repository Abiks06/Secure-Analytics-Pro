from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import io
from auth import verify_supabase_token
from database import get_supabase
from supabase import Client

app = FastAPI(title="Secure Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "ok", "message": "FastAPI backend is running!"}

@app.post("/upload")
async def upload_csv(
    file: UploadFile = File(...),
    user_payload: dict = Depends(verify_supabase_token),
    db: Client = Depends(get_supabase)
):
    # 1. Cyber Layer: File Type Validation
    if file.content_type != 'text/csv':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type: {file.content_type}. Only 'text/csv' is allowed."
        )
        
    try:
        # Read the file to content
        contents = await file.read()
        
        # 2. Data Science Layer: Read with Pandas
        # We use io.StringIO and decode because we have raw bytes
        csv_data = contents.decode('utf-8')
        df = pd.read_csv(io.StringIO(csv_data))
        
        # Return summary JSON
        return {
            "status": "success",
            "rows": len(df),
            "columns": df.columns.tolist(),
            "preview": df.head(5).to_dict(orient='records')
        }
        
    except UnicodeDecodeError:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not decode file as UTF-8. Please provide a valid CSV."
        )
    except pd.errors.EmptyDataError:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The provided CSV file is empty."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing file: {str(e)}"
        )
