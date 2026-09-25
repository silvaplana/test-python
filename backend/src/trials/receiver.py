import datetime
from typing import Literal, Optional

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from .trials import TrialCoursesFullError, Trials, TrialStudentNotFoundError


class StudentCreate(BaseModel):
    """Corps de POST /trials/students (ajout a la main depuis l'onglet)."""

    firstName: str
    lastName: str
    birthDate: Optional[datetime.date] = None
    gender: Optional[Literal["M", "F"]] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    parentName: Optional[str] = None
    comment: str = ""


class StudentUpdate(BaseModel):
    """Corps de PATCH /trials/students/{id} : seuls les champs presents sont
    modifies (null efface le champ)."""

    firstName: Optional[str] = None
    lastName: Optional[str] = None
    birthDate: Optional[datetime.date] = None
    gender: Optional[Literal["M", "F"]] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    parentName: Optional[str] = None
    comment: Optional[str] = None


class CourseAdd(BaseModel):
    """Corps de POST /trials/students/{id}/courses : date du cours
    (aujourd'hui si absente)."""

    date: Optional[datetime.date] = None


class CourseSet(BaseModel):
    """Corps de PUT /trials/students/{id}/courses/{number} : nouvelle date,
    ou null pour effacer ce cours."""

    date: Optional[datetime.date] = None


class CheckIn(BaseModel):
    """Corps de POST /trials/checkin : contenu du QR code scanne."""

    token: str


# Noms JSON (camelCase, comme le reste de l'API) -> colonnes de la base.
_FIELD_NAMES = {
    "firstName": "first_name",
    "lastName": "last_name",
    "birthDate": "birth_date",
    "gender": "gender",
    "email": "email",
    "phone": "phone",
    "parentName": "parent_name",
    "comment": "comment",
}


class TrialsReceiver:
    """Recoit les requetes REST (FastAPI) et delegue a Trials.

    Comme les autres receivers, enregistre ses routes sur une app FastAPI
    existante (partagee avec les autres modules), pas de service dedie. En
    realite le routeur protege par require_auth (voir app/main.py) : la page
    publique d'inscription aura ses propres routes, hors de ce routeur.
    """

    def __init__(self, client: Trials, app: FastAPI | APIRouter) -> None:
        self.client = client
        self.app = app
        self._register_routes()

    def _register_routes(self) -> None:
        self.app.get("/trials/students")(self.getStudents)
        self.app.post("/trials/students")(self.createStudent)
        self.app.patch("/trials/students/{student_id}")(self.updateStudent)
        self.app.delete("/trials/students/{student_id}")(self.deleteStudent)
        self.app.post("/trials/students/{student_id}/courses")(self.addCourse)
        self.app.put("/trials/students/{student_id}/courses/{number}")(self.setCourse)
        self.app.post("/trials/checkin")(self.checkIn)

    def getStudents(self) -> list[dict]:
        """Endpoint REST GET /trials/students. Tous les eleves en cours
        d'essai, le plus recemment inscrit en premier."""
        return self.client.list_students()

    def createStudent(self, request: StudentCreate) -> dict:
        """Endpoint REST POST /trials/students. Ajout a la main
        (exceptionnel, normalement via la page publique)."""
        fields = {_FIELD_NAMES[key]: value for key, value in request.model_dump().items()}
        try:
            return self.client.add_student(**fields)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def updateStudent(self, student_id: int, request: StudentUpdate) -> dict:
        """Endpoint REST PATCH /trials/students/{id}. Modifie les champs
        fournis (commentaire, identite...)."""
        fields = {_FIELD_NAMES[key]: value for key, value in request.model_dump(exclude_unset=True).items()}
        try:
            return self.client.update_student(student_id, fields)
        except TrialStudentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Élève inconnu") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def deleteStudent(self, student_id: int) -> dict:
        """Endpoint REST DELETE /trials/students/{id}."""
        try:
            self.client.delete_student(student_id)
        except TrialStudentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Élève inconnu") from exc
        return {"deleted": student_id}

    def addCourse(self, student_id: int, request: CourseAdd) -> dict:
        """Endpoint REST POST /trials/students/{id}/courses. Bouton "Ajouter
        cours d'essai" : remplit le 1er cours vide (409 si les 2 sont pris)."""
        try:
            return self.client.add_course(student_id, request.date)
        except TrialStudentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Élève inconnu") from exc
        except TrialCoursesFullError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def setCourse(self, student_id: int, number: int, request: CourseSet) -> dict:
        """Endpoint REST PUT /trials/students/{id}/courses/{number}. Corrige
        ou efface la date d'un cours."""
        try:
            return self.client.set_course(student_id, number, request.date)
        except TrialStudentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Élève inconnu") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def checkIn(self, request: CheckIn) -> dict:
        """Endpoint REST POST /trials/checkin. Scan du QR code d'un eleve en
        debut de cours (voir Trials.check_in pour les reponses possibles)."""
        return self.client.check_in(request.token)
