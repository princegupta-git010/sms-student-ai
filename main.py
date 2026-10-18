
import os
import re
import uuid
import secrets
from pathlib import Path
from sqlalchemy import select, func
from models import User, StudyMaterial, TimetableEntry
from fastapi import File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from fastapi import HTTPException
from pydantic import BaseModel, Field
from google import genai
from sqlalchemy import select
from models import ChatMessage
from models import StudyMaterial
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from models import TimetableEntry
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pwdlib import PasswordHash
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from database import Base, SessionLocal, engine
from models import User

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB

APP_SECRET = os.getenv("APP_SECRET", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
password_hash = PasswordHash.recommended()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip()

gemini_client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY and GEMINI_MODEL
    else None
)

if len(APP_SECRET) < 32:
    raise RuntimeError(
        "Set APP_SECRET in .env to a random secret of at least 32 characters."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    # Create the initial administrator once.
    if ADMIN_EMAIL and ADMIN_PASSWORD:
        with SessionLocal() as db:
            existing = db.scalar(
                select(User).where(User.email == ADMIN_EMAIL)
            )
            if existing is None:
                db.add(
                    User(
                        name="Administrator",
                        email=ADMIN_EMAIL,
                        password_hash=password_hash.hash(ADMIN_PASSWORD),
                        is_admin=True,
                    )
                )
                db.commit()

    yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="SMS Student AI",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET,
    session_cookie="sms_session",
    same_site="lax",
    https_only=False,  # Local development only; enable HTTPS for deployment.
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            request.session.clear()
            return None

        return {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": user.is_admin,
        }



def render_page(request: Request, template: str, **context):
    csrf_token = request.session.get("csrf_token")

    if not isinstance(csrf_token, str) or not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = csrf_token

    context["csrf_token"] = csrf_token

    return templates.TemplateResponse(
        request=request,
        name=template,
        context=context,
    )



@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)



@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    csrf_token = secrets.token_urlsafe(32)
    request.session["csrf_token"] = csrf_token

    return render_page(
        request,
        "register.html",
        error=None,
        csrf_token=csrf_token,
    )


@app.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
):
    expected_token = request.session.get("csrf_token")

    if (
        not isinstance(expected_token, str)
        or not secrets.compare_digest(csrf_token, expected_token)
    ):
        return render_page(
            request,
            "register.html",
            error="Your session expired or the form was invalid. Please try again.",
            csrf_token=expected_token or "",
        )

    name = name.strip()
    email = email.strip().lower()

    if not name or len(name) > 100:
        return render_page(
            request,
            "register.html",
            error="Enter a valid name (maximum 100 characters).",
            csrf_token=expected_token,
        )

    if len(email) > 255 or "@" not in email:
        return render_page(
            request,
            "register.html",
            error="Enter a valid email address.",
            csrf_token=expected_token,
        )

    if len(password) < 10:
        return render_page(
            request,
            "register.html",
            error="Use a password with at least 10 characters.",
            csrf_token=expected_token,
        )

    if password != confirm_password:
        return render_page(
            request,
            "register.html",
            error="The passwords do not match.",
            csrf_token=expected_token,
        )

    with SessionLocal() as db:
        existing = db.scalar(
            select(User).where(User.email == email)
        )

        if existing:
            return render_page(
                request,
                "register.html",
                error="An account with this email already exists.",
                csrf_token=expected_token,
            )

        user = User(
            name=name,
            email=email,
            password_hash=password_hash.hash(password),
            is_admin=False,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        user_id = user.id

    request.session.clear()
    request.session["user_id"] = user_id

    return RedirectResponse("/dashboard", status_code=303)



@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=303)

    csrf_token = secrets.token_urlsafe(32)
    request.session["csrf_token"] = csrf_token

    return render_page(
        request,
        "login.html",
        error=None,
        csrf_token=csrf_token,
    )

@limiter.limit("5/minute")
@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
):
    expected_token = request.session.get("csrf_token")

    if (
        not isinstance(expected_token, str)
        or not secrets.compare_digest(csrf_token, expected_token)
    ):
        return render_page(
            request,
            "login.html",
            error="Your session expired or the form was invalid. Please try again.",
            csrf_token=expected_token or "",
        )

    email = email.strip().lower()

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == email)
        )

        if user is None or not password_hash.verify(
            password, user.password_hash
        ):
            return render_page(
                request,
                "login.html",
                error="Incorrect email or password.",
                csrf_token=expected_token,
            )

        user_id = user.id

    request.session.clear()
    request.session["user_id"] = user_id

    return RedirectResponse("/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    return render_page(
        request,
        "dashboard.html",
        user=user,
    )



@app.post("/logout")
def logout(
    request: Request,
    csrf_token: str = Form(...),
):
    expected_token = request.session.get("csrf_token")

    if (
        not isinstance(expected_token, str)
        or not secrets.compare_digest(csrf_token, expected_token)
    ):
        return HTMLResponse(
            "Invalid or expired form token. Please refresh the page and try again.",
            status_code=403,
        )

    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@app.get("/materials", response_class=HTMLResponse)
def materials_page(request: Request):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        materials = (
            db.query(StudyMaterial)
            .order_by(StudyMaterial.created_at.desc())
            .all()
        )

    return render_page(
        request,
        "materials.html",
        user=user,
        materials=materials,
    )



@app.post("/materials/upload", response_class=HTMLResponse)
async def upload_material(
    request: Request,
    subject: str = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    csrf_token: str = Form(...),
):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user["is_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )

    expected_token = request.session.get("csrf_token")

    if (
        not isinstance(expected_token, str)
        or not secrets.compare_digest(csrf_token, expected_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired form token. Refresh the page and try again.",
        )

    subject = subject.strip()
    title = title.strip()

    if not subject or len(subject) > 150 or not title or len(title) > 200:
        raise HTTPException(
            status_code=400,
            detail="Invalid subject or title",
        )

    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed",
        )

    filename = f"{uuid.uuid4().hex}.pdf"
    destination = UPLOAD_DIR / filename
    size = 0
    header = b""

    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break

                if not header:
                    header = chunk[:5]

                size += len(chunk)
                if size > MAX_PDF_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF must be 10 MB or smaller",
                    )

                output.write(chunk)

        if not header.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail="The selected file is not a valid PDF",
            )

        with SessionLocal() as db:
            material = StudyMaterial(
                subject=subject,
                title=title,
                filename=filename,
                uploaded_by=user["id"],
            )
            db.add(material)
            db.commit()

    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return RedirectResponse("/materials", status_code=303)



@app.get("/materials/{material_id}/view")
def view_material(request: Request, material_id: int):
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        material = db.get(StudyMaterial, material_id)

        if material is None:
            raise HTTPException(status_code=404, detail="Material not found")

        path = UPLOAD_DIR / material.filename

        if not path.is_file() or path.parent.resolve() != UPLOAD_DIR.resolve():
            raise HTTPException(status_code=404, detail="PDF file not found")

        return FileResponse(
            path=path,
            media_type="application/pdf",
            filename=f"{material.title}.pdf",
            content_disposition_type="inline",
        )


@app.post("/materials/{material_id}/delete")
def delete_material(
    request: Request,
    material_id: int,
    csrf_token: str = Form(...),
):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user["is_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )

    expected_token = request.session.get("csrf_token")

    if (
        not isinstance(expected_token, str)
        or not secrets.compare_digest(csrf_token, expected_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired form token. Refresh the page and try again.",
        )

    with SessionLocal() as db:
        material = db.get(StudyMaterial, material_id)

        if material is None:
            raise HTTPException(
                status_code=404,
                detail="Material not found",
            )

        path = UPLOAD_DIR / material.filename
        db.delete(material)
        db.commit()

    path.unlink(missing_ok=True)

    return RedirectResponse("/materials", status_code=303)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    return render_page(request, "chat.html", user=user)


@app.get("/api/chat/history")
def chat_history(request: Request):
    user = current_user(request)

    if user is None:
        raise HTTPException(status_code=401, detail="Please log in again.")

    with SessionLocal() as db:
        history = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == user["id"])
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .limit(100)
        ).all()

        return {
            "messages": [
                {"role": item.role, "message": item.message}
                for item in history
            ]
        }

@limiter.limit("10/minute")
@app.post("/api/chat")
def send_chat_message(payload: ChatRequest, request: Request):
    user = current_user(request)

    if user is None:
        raise HTTPException(status_code=401, detail="Please log in again.")

    message = payload.message.strip()

    if not message:
        raise HTTPException(status_code=400, detail="Enter a question.")

    if gemini_client is None:
        raise HTTPException(
            status_code=503,
            detail="Gemini is not configured. Check GEMINI_API_KEY and GEMINI_MODEL in .env.",
        )

    with SessionLocal() as db:
        previous = db.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == user["id"])
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(12)
        ).all()

        conversation = [
            {
                "role": "user" if item.role == "user" else "model",
                "parts": [{"text": item.message}],
            }
            for item in reversed(previous)
        ]

        conversation.append({
            "role": "user",
            "parts": [{"text": message}],
        })

        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=conversation,
                config={
                    "system_instruction": (
                        '''You are SMS Student AI, a friendly and intelligent study companion
for students at the School of Management Sciences, Lucknow.

PERSONALITY:
- Sound natural, warm, encouraging, and conversational.
- Explain concepts like a helpful senior student, not a textbook.
- Avoid robotic introductions and repetitive phrases.
- Use simple English by default. Explain difficult terms clearly.
- Use emojis sparingly and only when they improve the response.

ANSWER STYLE:
- Answer the student's actual question first.
- Use clear headings, short paragraphs, and bullet points when helpful.
- Give practical examples, analogies, and memory tricks when relevant.
- For technical topics, explain the concept step by step.
- For exam questions, provide a suitable definition, key points,
  explanation, example, and conclusion when appropriate.
- For coding questions, explain the code and show examples where useful.
- Keep simple answers short; give detailed answers when requested.
- Use tables only when they make comparisons easier.
- Never invent college-specific information, schedules, or notices.
  If unsure, clearly say so and suggest how to verify it.
- Do not claim to have checked college records unless you actually have.

Make every reply useful, clear, encouraging, and appropriate for a
college student. Avoid unnecessary filler and repeated conclusions.'''
                    )
                },
            )

            reply = response.text

            if not reply:
                raise RuntimeError("Gemini returned an empty response.")

        except Exception:
            raise HTTPException(
                status_code=502,
                detail="The AI service could not answer right now. Check the server terminal and try again.",
            )

        db.add_all([
            ChatMessage(
                user_id=user["id"],
                role="user",
                message=message,
            ),
            ChatMessage(
                user_id=user["id"],
                role="assistant",
                message=reply,
            ),
        ])
        db.commit()

    return {"reply": reply}

TIMETABLE_DAYS = [
    "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday",
]



@app.get("/timetable", response_class=HTMLResponse)
def timetable_page(request: Request):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        entries = db.scalars(
            select(TimetableEntry).order_by(
                TimetableEntry.day,
                TimetableEntry.start_time,
            )
        ).all()

        timetable = [
            {
                "id": entry.id,
                "subject": entry.subject,
                "day": entry.day,
                "start_time": entry.start_time,
                "end_time": entry.end_time,
                "room": entry.room or "",
            }
            for entry in entries
        ]

    return render_page(
        request,
        "timetable.html",
        user=user,
        days=TIMETABLE_DAYS,
        timetable=timetable,
    )


@app.post("/timetable/add")
def add_timetable_entry(
    request: Request,
    subject: str = Form(...),
    day: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    room: str = Form(""),
    csrf_token: str = Form(...),
):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user["is_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )

    expected_token = request.session.get("csrf_token")

    if (
        not isinstance(expected_token, str)
        or not secrets.compare_digest(csrf_token, expected_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired form token. Refresh the page and try again.",
        )

    subject = subject.strip()
    room = room.strip()

    try:
        start = datetime.strptime(start_time, "%H:%M")
        end = datetime.strptime(end_time, "%H:%M")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid class time",
        )

    if (
        not subject
        or len(subject) > 150
        or len(room) > 100
        or day not in TIMETABLE_DAYS
        or end <= start
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid timetable entry",
        )

    with SessionLocal() as db:
        db.add(
            TimetableEntry(
                subject=subject,
                day=day,
                start_time=start_time,
                end_time=end_time,
                room=room,
            )
        )
        db.commit()

    return RedirectResponse("/timetable", status_code=303)


@app.post("/timetable/{entry_id}/delete")
def delete_timetable_entry(
    request: Request,
    entry_id: int,
    csrf_token: str = Form(...),
):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user["is_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Admin access required",
        )

    expected_token = request.session.get("csrf_token")

    if (
        not isinstance(expected_token, str)
        or not secrets.compare_digest(csrf_token, expected_token)
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired form token. Refresh the page and try again.",
        )

    with SessionLocal() as db:
        entry = db.get(TimetableEntry, entry_id)

        if entry is None:
            raise HTTPException(
                status_code=404,
                detail="Class not found",
            )

        db.delete(entry)
        db.commit()

    return RedirectResponse("/timetable", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    user = current_user(request)

    if user is None:
        return RedirectResponse("/login", status_code=303)

    if not user["is_admin"]:
        raise HTTPException(
            status_code=403,
            detail="Administrator access required",
        )

    with SessionLocal() as db:
        students = db.scalars(
            select(User).order_by(User.name.asc())
        ).all()

        student_list = [
            {
                "name": account.name,
                "email": account.email,
                "is_admin": account.is_admin,
            }
            for account in students
        ]

        student_count = db.scalar(
            select(func.count()).select_from(User)
        ) or 0

        material_count = db.scalar(
            select(func.count()).select_from(StudyMaterial)
        ) or 0

        timetable_count = db.scalar(
            select(func.count()).select_from(TimetableEntry)
        ) or 0

    return render_page(
        request,
        "admin.html",
        user=user,
        students=student_list,
        student_count=student_count,
        material_count=material_count,
        timetable_count=timetable_count,
    )

