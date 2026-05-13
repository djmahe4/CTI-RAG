from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rag.api.routers import router

# Import route # This line is important
fastapi_server = FastAPI()
fastapi_server.include_router(router)

# Configure CORS
fastapi_server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Specify explicitly the allowed front-end source
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@fastapi_server.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "accelerometer=(), camera=(), microphone=(), geolocation=()"
    return response

# Add route

@fastapi_server.get("/")
async def root():
    return {"message": "status", "status": "ok"}


@fastapi_server.get("/health")
async def health():
    return {"message": "status", "status": "ok"}
