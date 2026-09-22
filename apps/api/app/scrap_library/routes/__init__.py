# -*- coding: utf-8 -*-
"""Scrap-library HTTP routes (embed / enrich / actress)."""
from fastapi import APIRouter

from .actress_routes import router as actress_router
from .embed_routes import router as embed_router
from .enrich_routes import router as enrich_router

router = APIRouter()
router.include_router(embed_router)
router.include_router(enrich_router)
router.include_router(actress_router)
