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
DROPBOX_OAUTH_TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DROPBOX_ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN", "").strip()
DROPBOX_REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN", "").strip()
DROPBOX_APP_KEY = os.environ.get("DROPBOX_APP_KEY", "").strip()
DROPBOX_APP_SECRET = os.environ.get("DROPBOX_APP_SECRET", "").strip()
VISUAL_PROXY_API_KEY = os.environ.get("VISUAL_PROXY_API_KEY", "").strip()
DROPBOX_OUTPUT_ROOT = os.environ.get(
    "DROPBOX_OUTPUT_ROOT",
    "/ENEM 2026 App/ULTIMATE_ENEM_DR_IMAGEM_PIPELINE/02_DR_IMAGEM_PARA_CODEX_PERFEITAS",
).strip()
DEFAULT_RENDER_DPI = env_int("DEFAULT_RENDER_DPI", 220)
_dropbox_access_token_cache = DROPBOX_ACCESS_TOKEN

app = FastAPI(
    title="ultimateENEM Visual Proxy",
    version="1.1.2",
    description="Proxy para localizar PDFs no Dropbox, renderizar paginas, recortar recursos visuais e salvar PNG/WebP.",
)


def require_proxy_auth(authorization: str | None = Header(default=None)) -> None:
    if not VISUAL_PROXY_API_KEY:
        raise HTTPException(status_code=500, detail="VISUAL_PROXY_API_KEY nao foi configurada no servidor.")
    if authorization != f"Bearer {VISUAL_PROXY_API_KEY}":
        raise HTTPException(status_code=401, detail="Chave do proxy ausente ou invalida.")


def dropbox_refresh_configured() -> bool:
    return bool(DROPBOX_REFRESH_TOKEN and DROPBOX_APP_KEY and DROPBOX_APP_SECRET)


async def refresh_dropbox_access_token() -> str:
    if not dropbox_refresh_configured():
        raise HTTPException(
            status_code=500,
            detail="Configure DROPBOX_REFRESH_TOKEN, DROPBOX_APP_KEY e DROPBOX_APP_SECRET no Render.",
        )
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            DROPBOX_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": DROPBOX_REFRESH_TOKEN,
                "client_id": DROPBOX_APP_KEY,
                "client_secret": DROPBOX_APP_SECRET,
            },
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={"dropbox_oauth_status": response.status_code, "dropbox_oauth_response": response.text},
        )
    access_token = response.json().get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Dropbox OAuth nao retornou access_token ao renovar.")
    global _dropbox_access_token_cache
    _dropbox_access_token_cache = access_token
    return access_token


async def get_dropbox_access_token(force_refresh: bool = False) -> str:
    if force_refresh or not _dropbox_access_token_cache:
        if dropbox_refresh_configured():
            return await refresh_dropbox_access_token()
    if _dropbox_access_token_cache:
        return _dropbox_access_token_cache
    raise HTTPException(
        status_code=500,
        detail="Configure DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET, ou DROPBOX_ACCESS_TOKEN para teste.",
    )


def clean_filename(value: str, default: str = "arquivo") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip("-._")
    return normalized or default


def dropbox_join(folder: str, filename: str) -> str:
    return posixpath.join("/" + folder.strip("/"), filename)


def image_to_bytes(image: Image.Image, image_format: Literal["png", "webp"], quality: int = 88) -> bytes:
    buffer = io.BytesIO()
    if image_format == "webp":
        image.save(buffer, format="WEBP", quality=quality, method=6)
    else:
        image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def dropbox_json(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    async def call(token: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=60.0) as client:
            return await client.post(
                f"{DROPBOX_API}{endpoint}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )

    response = await call(await get_dropbox_access_token())
    if response.status_code == status.HTTP_401_UNAUTHORIZED and dropbox_refresh_configured():
        response = await call(await refresh_dropbox_access_token())
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail={"dropbox_status": response.status_code, "dropbox_response": response.text})
    return response.json()


async def dropbox_download(path: str) -> bytes:
    async def call(token: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=120.0) as client:
            return await client.post(
                f"{DROPBOX_CONTENT_API}/files/download",
                headers={"Authorization": f"Bearer {token}", "Dropbox-API-Arg": json.dumps({"path": path}, ensure_ascii=True)},
            )

    response = await call(await get_dropbox_access_token())
    if response.status_code == status.HTTP_401_UNAUTHORIZED and dropbox_refresh_configured():
        response = await call(await refresh_dropbox_access_token())
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail={"dropbox_status": response.status_code, "dropbox_response": response.text})
    return response.content


async def dropbox_upload(path: str, data: bytes) -> dict[str, Any]:
    arg = {"path": path, "mode": "overwrite", "autorename": False, "mute": True, "strict_conflict": False}

    async def call(token: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=120.0) as client:
            return await client.post(
                f"{DROPBOX_CONTENT_API}/files/upload",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                    "Dropbox-API-Arg": json.dumps(arg, ensure_ascii=True),
                },
                content=data,
            )

    response = await call(await get_dropbox_access_token())
    if response.status_code == status.HTTP_401_UNAUTHORIZED and dropbox_refresh_configured():
        response = await call(await refresh_dropbox_access_token())
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail={"dropbox_status": response.status_code, "dropbox_response": response.text})
    return response.json()


async def dropbox_temporary_link(path: str) -> dict[str, Any]:
    return await dropbox_json("/files/get_temporary_link", {"path": path})


def render_pdf_page(pdf_bytes: bytes, page_number: int, dpi: int) -> Image.Image:
    if page_number < 1:
        raise HTTPException(status_code=400, detail="page_number deve comecar em 1.")
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF invalido ou ilegivel: {exc}") from exc
    page_index = page_number - 1
    if page_index >= len(document):
        raise HTTPException(status_code=400, detail=f"PDF tem {len(document)} paginas; page_number={page_number} nao existe.")
    page = document[page_index]
    pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
    return ImageOps.exif_transpose(Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB"))


class HealthResponse(BaseModel):
    ok: bool
    service: str
    dropbox_token_configured: bool
    dropbox_refresh_configured: bool
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


class DropboxRefreshTestResponse(BaseModel):
    ok: bool
    message: str
    dropbox_refresh_configured: bool


class RenderPageRequest(BaseModel):
    pdf_path: str = Field(..., description="Caminho completo do PDF no Dropbox.")
    page_number: int = Field(..., ge=1, description="Numero da pagina do PDF, iniciando em 1.")
    dpi: int = Field(DEFAULT_RENDER_DPI, ge=96, le=360)
    output_folder: str | None = Field(None, description="Pasta Dropbox de saida; se vazio usa DROPBOX_OUTPUT_ROOT.")
    output_name: str | None = Field(None, description="Nome base do arquivo sem extensao.")
    image_format: Literal["png", "webp"] = "png"
    webp_quality: int = Field(88, ge=40, le=100)


class BBox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class CropRequest(BaseModel):
    pdf_path: str = Field(..., description="Caminho completo do PDF no Dropbox.")
    page_number: int = Field(..., ge=1, description="Numero da pagina do PDF, iniciando em 1.")
    bbox: BBox
    units: Literal["normalized", "pixels"] = Field("normalized", description="normalized usa x/y/w/h entre 0 e 1.")
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
        dropbox_token_configured=bool(_dropbox_access_token_cache or dropbox_refresh_configured()),
        dropbox_refresh_configured=dropbox_refresh_configured(),
        output_root=DROPBOX_OUTPUT_ROOT,
    )


@app.post("/v1/dropbox/test-refresh", response_model=DropboxRefreshTestResponse, dependencies=[Depends(require_proxy_auth)])
async def test_dropbox_refresh() -> DropboxRefreshTestResponse:
    await refresh_dropbox_access_token()
    return DropboxRefreshTestResponse(
        ok=True,
        message="Dropbox OAuth renovou access_token com sucesso pelo proxy.",
        dropbox_refresh_configured=dropbox_refresh_configured(),
    )


@app.post("/v1/dropbox/search", response_model=DropboxSearchResponse, dependencies=[Depends(require_proxy_auth)])
async def dropbox_search(request: DropboxSearchRequest) -> DropboxSearchResponse:
    payload = {"query": request.query, "options": {"path": request.path, "max_results": request.max_results, "filename_only": False, "file_status": "active"}}
    data = await dropbox_json("/files/search_v2", payload)
    matches: list[DropboxSearchMatch] = []
    for item in data.get("matches", []):
        metadata = item.get("metadata", {}).get("metadata", {})
        if metadata.get("path_display"):
            matches.append(DropboxSearchMatch(name=metadata.get("name", ""), path_display=metadata["path_display"], id=metadata.get("id"), client_modified=metadata.get("client_modified")))
    return DropboxSearchResponse(matches=matches)


@app.post("/v1/pdf/render-page", response_model=VisualOperationResponse, dependencies=[Depends(require_proxy_auth)])
async def render_page(request: RenderPageRequest) -> VisualOperationResponse:
    image = render_pdf_page(await dropbox_download(request.pdf_path), request.page_number, request.dpi)
    output_folder = request.output_folder or DROPBOX_OUTPUT_ROOT
    base_name = clean_filename(request.output_name or f"{clean_filename(posixpath.basename(request.pdf_path))}_p{request.page_number:03d}")
    data = image_to_bytes(image, request.image_format, request.webp_quality)
    dropbox_path = dropbox_join(output_folder, f"{base_name}.{request.image_format}")
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
        assets=[UploadedAsset(format=request.image_format, dropbox_path=dropbox_path, temporary_link=link_data["link"], bytes=len(data), width=image.width, height=image.height)],
    )


def resolve_crop_box(image: Image.Image, bbox: BBox, units: str, pad_px: int) -> tuple[int, int, int, int]:
    if units == "normalized":
        x1, y1 = round(bbox.x * image.width), round(bbox.y * image.height)
        x2, y2 = round((bbox.x + bbox.w) * image.width), round((bbox.y + bbox.h) * image.height)
    else:
        x1, y1, x2, y2 = round(bbox.x), round(bbox.y), round(bbox.x + bbox.w), round(bbox.y + bbox.h)
    x1, y1 = max(0, x1 - pad_px), max(0, y1 - pad_px)
    x2, y2 = min(image.width, x2 + pad_px), min(image.height, y2 + pad_px)
    if x2 <= x1 or y2 <= y1:
        raise HTTPException(status_code=400, detail="bbox invalido: largura/altura precisa ser positiva.")
    return x1, y1, x2, y2


@app.post("/v1/pdf/crop", response_model=VisualOperationResponse, dependencies=[Depends(require_proxy_auth)])
async def crop_pdf_visual(request: CropRequest) -> VisualOperationResponse:
    if not request.make_png and not request.make_webp:
        raise HTTPException(status_code=400, detail="Ative make_png ou make_webp.")
    page_image = render_pdf_page(await dropbox_download(request.pdf_path), request.page_number, request.dpi)
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
        assets.append(UploadedAsset(format=image_format, dropbox_path=dropbox_path, temporary_link=link_data["link"], bytes=len(data), width=cropped.width, height=cropped.height))
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
