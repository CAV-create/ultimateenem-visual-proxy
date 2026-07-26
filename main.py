from __future__ import annotations

import io
import json
import os
import posixpath
import re
import unicodedata
from typing import Any, Literal

import fitz
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, status
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


DROPBOX_API = "https://api.dropboxapi.com/2"
DROPBOX_CONTENT_API = "https://content.dropboxapi.com/2"


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DROPBOX_ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN", "")
VISUAL_PROXY_API_KEY = os.environ.get("VISUAL_PROXY_API_KEY", "")
DROPBOX_OUTPUT_ROOT = os.environ.get(
    "DROPBOX_OUTPUT_ROOT",
    "/ENEM 2026 App/ULTIMATE_ENEM_DR_IMAGEM_PIPELINE/02_DR_IMAGEM_PARA_CODEX_PERFEITAS",
)
DEFAULT_RENDER_DPI = env_int("DEFAULT_RENDER_DPI", 220)


app = FastAPI(
    title="ultimateENEM Visual Proxy",
    version="1.0.0",
    description=(
        "Proxy do ultimateENEM para baixar PDFs do Dropbox, renderizar paginas, "
        "recortar recursos visuais e salvar PNG/WebP de volta no Dropbox."
    ),
)


def require_proxy_auth(authorization: str | None = Header(default=None)) -> None:
    if not VISUAL_PROXY_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="VISUAL_PROXY_API_KEY nao foi configurada no servidor.",
        )
    expected = f"Bearer {VISUAL_PROXY_API_KEY}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave do proxy ausente ou invalida.",
        )


def require_dropbox_token() -> str:
    if not DROPBOX_ACCESS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DROPBOX_ACCESS_TOKEN nao foi configurado no servidor.",
        )
    return DROPBOX_ACCESS_TOKEN


def clean_filename(value: str, default: str = "arquivo") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip("-._")
    return normalized or default


def dropbox_join(folder: str, filename: str) -> str:
    folder = "/" + folder.strip("/")
    return posixpath.join(folder, filename)


def image_to_bytes(image: Image.Image, image_format: Literal["png", "webp"], quality: int = 88) -> bytes:
    buffer = io.BytesIO()
    if image_format == "webp":
        image.save(buffer, format="WEBP", quality=quality, method=6)
    else:
        image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def dropbox_post_json(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = require_dropbox_token()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{DROPBOX_API}{endpoint}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"dropbox_status": response.status_code, "dropbox_response": response.text},
        )
    return response.json()


async def dropbox_download(path: str) -> bytes:
    token = require_dropbox_token()
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{DROPBOX_CONTENT_API}/files/download",
            headers={
                "Authorization": f"Bearer {token}",
                "Dropbox-API-Arg": json.dumps({"path": path}, ensure_ascii=True),
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"dropbox_status": response.status_code, "dropbox_response": response.text},
        )
    return response.content


async def dropbox_upload(path: str, data: bytes) -> dict[str, Any]:
    token = require_dropbox_token()
    arg = {
        "path": path,
        "mode": "overwrite",
        "autorename": False,
        "mute": True,
        "strict_conflict": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{DROPBOX_CONTENT_API}/files/upload",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
                "Dropbox-API-Arg": json.dumps(arg, ensure_ascii=True),
            },
            content=data,
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"dropbox_status": response.status_code, "dropbox_response": response.text},
        )
    return response.json()


async def dropbox_temporary_link(path: str) -> dict[str, Any]:
    return await dropbox_post_json("/files/get_temporary_link", {"path": path})


def render_pdf_page(pdf_bytes: bytes, page_number: int, dpi: int) -> Image.Image:
    if page_number < 1:
        raise HTTPException(status_code=400, detail="page_number deve comecar em 1.")
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pragma: no cover - depende de PDF externo
        raise HTTPException(status_code=400, detail=f"PDF invalido ou ilegivel: {exc}") from exc
    page_index = page_number - 1
    if page_index >= len(document):
        raise HTTPException(
            status_code=400,
            detail=f"PDF tem {len(document)} paginas; page_number={page_number} nao existe.",
        )
    page = document[page_index]
    matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    return ImageOps.exif_transpose(image)


class HealthResponse(BaseModel):
    ok: bool
    service: str
    dropbox_token_configured: bool
    output_root: str


class DropboxSearchRequest(BaseModel):
    query: str = Field(..., description="Nome parcial do PDF ou trecho do caminho.")
    path: str = Field("/ENEM 2026 App", description="Pasta inicial do Dropbox para busca.")
    max_results: int = Field(10, ge=1, le=50)


class DropboxSearchMatch(BaseModel):
    name: str
    path_display: str
    id: str | None = None
    client_modified: str | None = None


class DropboxSearchResponse(BaseModel):
    matches: list[DropboxSearchMatch]


class RenderPageRequest(BaseModel):
    pdf_path: str = Field(..., description="Caminho completo do PDF no Dropbox.")
    page_number: int = Field(..., ge=1, description="Numero da pagina do PDF, iniciando em 1.")
    dpi: int = Field(DEFAULT_RENDER_DPI, ge=96, le=360)
    output_folder: str | None = Field(None, description="Pasta Dropbox de saida; se vazio usa DROPBOX_OUTPUT_ROOT.")
    output_name: str | None = Field(None, description="Nome base do arquivo sem extensao.")
    image_format: Literal["png", "webp"] = "png"
    webp_quality: int = Field(88, ge=40, le=100)


class BBox(BaseModel):
    x: float = Field(..., description="Esquerda do recorte.")
    y: float = Field(..., description="Topo do recorte.")
    w: float = Field(..., description="Largura do recorte.")
    h: float = Field(..., description="Altura do recorte.")


class CropRequest(BaseModel):
    pdf_path: str = Field(..., description="Caminho completo do PDF no Dropbox.")
    page_number: int = Field(..., ge=1, description="Numero da pagina do PDF, iniciando em 1.")
    bbox: BBox = Field(..., description="Retangulo de recorte.")
    units: Literal["normalized", "pixels"] = Field(
        "normalized",
        description="normalized usa x/y/w/h entre 0 e 1; pixels usa coordenadas da pagina renderizada.",
    )
    dpi: int = Field(DEFAULT_RENDER_DPI, ge=96, le=360)
    pad_px: int = Field(10, ge=0, le=120, description="Sangria branca controlada no recorte.")
    output_folder: str | None = Field(None, description="Pasta Dropbox de saida; se vazio usa DROPBOX_OUTPUT_ROOT.")
    output_basename: str = Field(..., description="Nome base dos arquivos gerados sem extensao.")
    make_png: bool = True
    make_webp: bool = True
    webp_quality: int = Field(88, ge=40, le=100)


class UploadedAsset(BaseModel):
    format: Literal["png", "webp"]
    dropbox_path: str
    temporary_link: str
    bytes: int
    width: int
    height: int


class VisualOperationResponse(BaseModel):
    status: Literal["ok"]
    pdf_path: str
    page_number: int
    dpi: int
    page_width: int
    page_height: int
    crop_box_pixels: list[int] = Field(default_factory=list)
    assets: list[UploadedAsset]


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        ok=True,
        service="ultimateENEM Visual Proxy",
        dropbox_token_configured=bool(DROPBOX_ACCESS_TOKEN),
        output_root=DROPBOX_OUTPUT_ROOT,
    )


@app.post(
    "/v1/dropbox/search",
    response_model=DropboxSearchResponse,
    dependencies=[Depends(require_proxy_auth)],
)
async def dropbox_search(request: DropboxSearchRequest) -> DropboxSearchResponse:
    payload = {
        "query": request.query,
        "options": {
            "path": request.path,
            "max_results": request.max_results,
            "filename_only": False,
            "file_status": "active",
        },
    }
    data = await dropbox_post_json("/files/search_v2", payload)
    matches: list[DropboxSearchMatch] = []
    for item in data.get("matches", []):
        metadata = item.get("metadata", {}).get("metadata", {})
        path_display = metadata.get("path_display")
        if not path_display:
            continue
        matches.append(
            DropboxSearchMatch(
                name=metadata.get("name", ""),
                path_display=path_display,
                id=metadata.get("id"),
                client_modified=metadata.get("client_modified"),
            )
        )
    return DropboxSearchResponse(matches=matches)


@app.post(
    "/v1/pdf/render-page",
    response_model=VisualOperationResponse,
    dependencies=[Depends(require_proxy_auth)],
)
async def render_page(request: RenderPageRequest) -> VisualOperationResponse:
    pdf_bytes = await dropbox_download(request.pdf_path)
    image = render_pdf_page(pdf_bytes, request.page_number, request.dpi)
    output_folder = request.output_folder or DROPBOX_OUTPUT_ROOT
    base_name = request.output_name or f"{clean_filename(posixpath.basename(request.pdf_path))}_p{request.page_number:03d}"
    extension = request.image_format
    data = image_to_bytes(image, extension, request.webp_quality)
    dropbox_path = dropbox_join(output_folder, f"{clean_filename(base_name)}.{extension}")
    await dropbox_upload(dropbox_path, data)
    link_data = await dropbox_temporary_link(dropbox_path)
    return VisualOperationResponse(
        status="ok",
        pdf_path=request.pdf_path,
        page_number=request.page_number,
        dpi=request.dpi,
        page_width=image.width,
        page_height=image.height,
        crop_box_pixels=[],
        assets=[
            UploadedAsset(
                format=extension,
                dropbox_path=dropbox_path,
                temporary_link=link_data["link"],
                bytes=len(data),
                width=image.width,
                height=image.height,
            )
        ],
    )


def resolve_crop_box(image: Image.Image, bbox: BBox, units: str, pad_px: int) -> tuple[int, int, int, int]:
    if units == "normalized":
        x1 = round(bbox.x * image.width)
        y1 = round(bbox.y * image.height)
        x2 = round((bbox.x + bbox.w) * image.width)
        y2 = round((bbox.y + bbox.h) * image.height)
    else:
        x1 = round(bbox.x)
        y1 = round(bbox.y)
        x2 = round(bbox.x + bbox.w)
        y2 = round(bbox.y + bbox.h)
    x1 = max(0, x1 - pad_px)
    y1 = max(0, y1 - pad_px)
    x2 = min(image.width, x2 + pad_px)
    y2 = min(image.height, y2 + pad_px)
    if x2 <= x1 or y2 <= y1:
        raise HTTPException(status_code=400, detail="bbox invalido: largura/altura precisa ser positiva.")
    return x1, y1, x2, y2


@app.post(
    "/v1/pdf/crop",
    response_model=VisualOperationResponse,
    dependencies=[Depends(require_proxy_auth)],
)
async def crop_pdf_visual(request: CropRequest) -> VisualOperationResponse:
    if not request.make_png and not request.make_webp:
        raise HTTPException(status_code=400, detail="Ative make_png ou make_webp.")
    pdf_bytes = await dropbox_download(request.pdf_path)
    page_image = render_pdf_page(pdf_bytes, request.page_number, request.dpi)
    crop_box = resolve_crop_box(page_image, request.bbox, request.units, request.pad_px)
    cropped = page_image.crop(crop_box)
    output_folder = request.output_folder or DROPBOX_OUTPUT_ROOT
    base_name = clean_filename(request.output_basename)
    assets: list[UploadedAsset] = []
    for image_format in (["png"] if request.make_png else []) + (["webp"] if request.make_webp else []):
        suffix = "_app" if image_format == "webp" else ""
        data = image_to_bytes(cropped, image_format, request.webp_quality)
        dropbox_path = dropbox_join(output_folder, f"{base_name}{suffix}.{image_format}")
        await dropbox_upload(dropbox_path, data)
        link_data = await dropbox_temporary_link(dropbox_path)
        assets.append(
            UploadedAsset(
                format=image_format,
                dropbox_path=dropbox_path,
                temporary_link=link_data["link"],
                bytes=len(data),
                width=cropped.width,
                height=cropped.height,
            )
        )
    return VisualOperationResponse(
        status="ok",
        pdf_path=request.pdf_path,
        page_number=request.page_number,
        dpi=request.dpi,
        page_width=page_image.width,
        page_height=page_image.height,
        crop_box_pixels=list(crop_box),
        assets=assets,
    )
