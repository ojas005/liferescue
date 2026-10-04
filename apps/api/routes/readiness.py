"""Personal emergency readiness & prevention endpoints (Capability C)."""

from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.dependencies import get_db, get_orchestrator
from apps.api.schemas import (
    CreateContactRequest,
    UpdateContactRequest,
    UpdateProfileRequest,
)
from packages.domain.models import (
    EmergencyContact,
    EmergencyProfile,
    ReadinessAssessment,
)
from packages.domain.orchestrator import ResponseOrchestrator
from packages.storage.sqlite_repo import SQLiteDatabase

router = APIRouter(tags=["Readiness & Prevention"])


@router.get("/emergency-profile", response_model=EmergencyProfile)
def get_emergency_profile(
    db: Annotated[SQLiteDatabase, Depends(get_db)],
    user_id: str = Query(default="usr_demo"),
) -> EmergencyProfile:
    """Retrieve user's emergency profile."""
    prof = db.get_profile(user_id)
    if not prof:
        prof = EmergencyProfile(user_id=user_id)
        db.save_profile(prof)
    return prof


@router.put("/emergency-profile", response_model=EmergencyProfile)
def update_emergency_profile(
    req: UpdateProfileRequest,
    db: Annotated[SQLiteDatabase, Depends(get_db)],
    user_id: str = Query(default="usr_demo"),
) -> EmergencyProfile:
    """Update medical history, allergies, blood type, and emergency directives."""
    prof = EmergencyProfile(
        user_id=user_id,
        blood_type=req.blood_type,
        allergies=req.allergies,
        medications=req.medications,
        medical_conditions=req.medical_conditions,
        emergency_instructions=req.emergency_instructions,
        primary_language=req.primary_language,
        home_address=req.home_address,
    )
    return db.save_profile(prof)


@router.get("/contacts", response_model=list[EmergencyContact])
def list_contacts(
    db: Annotated[SQLiteDatabase, Depends(get_db)],
    user_id: str = Query(default="usr_demo"),
) -> list[EmergencyContact]:
    """List designated emergency contacts."""
    return db.list_for_user(user_id)


@router.post(
    "/contacts", response_model=EmergencyContact, status_code=status.HTTP_201_CREATED
)
def create_contact(
    req: CreateContactRequest,
    db: Annotated[SQLiteDatabase, Depends(get_db)],
    user_id: str = Query(default="usr_demo"),
) -> EmergencyContact:
    """Add a new emergency contact."""
    contact = EmergencyContact(
        user_id=user_id,
        name=req.name,
        relationship=req.relationship,
        phone=req.phone,
        email=req.email,
        is_primary=req.is_primary,
        notify_on_escalation=req.notify_on_escalation,
    )
    return db.create_contact(contact)


@router.put("/contacts/{contact_id}", response_model=EmergencyContact)
def update_contact(
    contact_id: str,
    req: UpdateContactRequest,
    db: Annotated[SQLiteDatabase, Depends(get_db)],
) -> EmergencyContact:
    """Update an existing emergency contact."""
    existing = db.get_contact(contact_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact '{contact_id}' not found",
        )

    if req.name is not None:
        existing.name = req.name
    if req.relationship is not None:
        existing.relationship = req.relationship
    if req.phone is not None:
        existing.phone = req.phone
    if req.email is not None:
        existing.email = req.email
    if req.is_primary is not None:
        existing.is_primary = req.is_primary
    if req.notify_on_escalation is not None:
        existing.notify_on_escalation = req.notify_on_escalation

    return db.update_contact(existing)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(
    contact_id: str,
    db: Annotated[SQLiteDatabase, Depends(get_db)],
) -> None:
    """Remove an emergency contact."""
    deleted = db.delete_contact(contact_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact '{contact_id}' not found",
        )


@router.get("/readiness", response_model=ReadinessAssessment)
def get_readiness_assessment(
    orch: Annotated[ResponseOrchestrator, Depends(get_orchestrator)],
    user_id: str = Query(default="usr_demo"),
) -> ReadinessAssessment:
    """Compute preparedness score, gap analysis, and readiness recommendations."""
    return orch.assess_user_readiness(user_id=user_id)
