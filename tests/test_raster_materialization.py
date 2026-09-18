from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from PIL import Image
import yaml

import main


def make_jpeg_bytes() -> bytes:
    image = Image.new("RGB", (120, 80), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class RasterMaterializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_jpg_is_materialized_to_real_treated_assets(self) -> None:
        request = main.RasterMaterializeRequest(
            source_path="/originais/questao.jpg",
            output_basename="questao_tratada",
        )

        with (
            patch.object(main, "dropbox_download", AsyncMock(return_value=make_jpeg_bytes())),
            patch.object(main, "dropbox_upload", AsyncMock(return_value={})) as upload,
            patch.object(
                main,
                "dropbox_temporary_link",
                AsyncMock(side_effect=lambda path: {"link": f"https://example.test{path}"}),
            ),
        ):
            response = await main.materialize_raster_visual(request)

        self.assertEqual(response.status, "ok")
        self.assertEqual(response.crop_box_pixels, [0, 0, 120, 80])
        self.assertEqual(len(response.assets), 2)
        self.assertTrue(all("/tratadas/" in asset.dropbox_path for asset in response.assets))
        self.assertEqual(upload.await_count, 2)
        self.assertIn("full_frame_preserved", response.processing_steps)

    async def test_pdf_is_rejected_by_raster_route(self) -> None:
        request = main.RasterMaterializeRequest(
            source_path="/originais/questao.pdf",
            output_basename="questao_tratada",
        )

        with patch.object(main, "dropbox_download", AsyncMock(return_value=b"not-an-image")):
            with self.assertRaises(HTTPException) as raised:
                await main.materialize_raster_visual(request)

        self.assertEqual(raised.exception.status_code, 400)

    def test_output_folder_must_be_a_final_image_folder(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            main.resolve_treated_output_folder("/ENEM 2026 App/brutos")

        self.assertEqual(raised.exception.status_code, 400)

    def test_static_action_schema_exposes_raster_materialization(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "openapi_gpt_action_visual_proxy.yaml"
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        operation = schema["paths"]["/v1/image/materialize"]["post"]

        self.assertEqual(operation["operationId"], "materializar_imagem_tratada")
        self.assertEqual(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/RasterOperationResponse",
        )


if __name__ == "__main__":
    unittest.main()
