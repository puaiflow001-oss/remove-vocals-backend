from fastapi import FastAPI

app = FastAPI(title="Remove Vocals AI")

@app.get("/")
def home():
    return {"message": "Remove Vocals AI Server is running!"}

@app.get("/health")
def health():
    return {"status": "online"}
