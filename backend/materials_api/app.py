"""FastAPI application for Crystal Material Universe."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .models import ApiStatus, SearchResponse, parse_csv, parse_element_csv
from .ovito_renderer import OvitoRenderError, OvitoRenderService, RenderOptions
from .repository import MaterialRepository, SearchQuery
from .structure import StructureParseError, parse_cif_structure


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def create_app(
    *,
    database_path: str | Path,
    blob_path: str | Path,
    renderer: OvitoRenderService | None = None,
    frontend_dir: str | Path | None = None,
) -> FastAPI:
    database_path = Path(database_path)
    blob_path = Path(blob_path)
    render_service = renderer or OvitoRenderService(database_path.parent / "renders")
    app = FastAPI(
        title="Crystal Material Universe API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def repository() -> MaterialRepository:
        if not database_path.is_file() or not blob_path.is_file():
            raise _error(503, "index_not_ready", "The materials index has not been built yet")
        return MaterialRepository(database_path, blob_path)

    @app.get("/api/health", response_model=ApiStatus)
    async def health() -> ApiStatus:
        return ApiStatus(
            index_ready=database_path.is_file() and blob_path.is_file(),
            ovito_available=render_service.available(),
        )

    @app.get("/api/stats")
    async def stats():
        def load_stats():
            with repository() as repo:
                result = repo.stats()
            return result

        result = load_stats()
        result["ovito_available"] = render_service.available()
        return result

    @app.get("/api/materials", response_model=SearchResponse)
    async def search_materials(
        elements: str = "",
        exclude: str = "",
        element_mode: Literal["all", "any", "exact"] = "all",
        datasets: str = "",
        formula: str | None = None,
        gap_min: float | None = None,
        gap_max: float | None = None,
        density_min: float | None = None,
        density_max: float | None = None,
        volume_min: float | None = None,
        volume_max: float | None = None,
        n_atoms_min: float | None = None,
        n_atoms_max: float | None = None,
        n_elements_min: int | None = None,
        n_elements_max: int | None = None,
        spacegroups: str = "",
        crystal_systems: str = "",
        formation_energy_min: float | None = None,
        formation_energy_max: float | None = None,
        e_hull_min: float | None = None,
        e_hull_max: float | None = None,
        stability: Literal["stable", "unstable"] | None = None,
        metallicity: Literal["metal", "nonmetal"] | None = None,
        magnetic_orderings: str = "",
        magnetization_min: float | None = None,
        magnetization_max: float | None = None,
        bulk_modulus_min: float | None = None,
        bulk_modulus_max: float | None = None,
        shear_modulus_min: float | None = None,
        shear_modulus_max: float | None = None,
        has_properties: str = "",
        page: int = Query(1, ge=1),
        page_size: int = Query(24, ge=1, le=100),
        sort: str = "material_id",
        direction: Literal["asc", "desc"] = "asc",
    ) -> SearchResponse:
        try:
            spg = tuple(int(value) for value in parse_csv(spacegroups))
            query = SearchQuery(
                include_elements=parse_element_csv(elements),
                exclude_elements=parse_element_csv(exclude),
                element_mode=element_mode,
                datasets=parse_csv(datasets),
                formula=formula,
                gap_min=gap_min,
                gap_max=gap_max,
                density_min=density_min,
                density_max=density_max,
                volume_min=volume_min,
                volume_max=volume_max,
                n_atoms_min=n_atoms_min,
                n_atoms_max=n_atoms_max,
                n_elements_min=n_elements_min,
                n_elements_max=n_elements_max,
                spacegroup_numbers=spg,
                crystal_systems=parse_csv(crystal_systems),
                formation_energy_min=formation_energy_min,
                formation_energy_max=formation_energy_max,
                e_hull_min=e_hull_min,
                e_hull_max=e_hull_max,
                stability=stability,
                metallicity=metallicity,
                magnetic_orderings=parse_csv(magnetic_orderings),
                magnetization_min=magnetization_min,
                magnetization_max=magnetization_max,
                bulk_modulus_min=bulk_modulus_min,
                bulk_modulus_max=bulk_modulus_max,
                shear_modulus_min=shear_modulus_min,
                shear_modulus_max=shear_modulus_max,
                has_properties=parse_csv(has_properties),
                page=page,
                page_size=page_size,
                sort=sort,
                direction=direction,
            )
            with repository() as repo:
                result = repo.search(query)
        except (TypeError, ValueError) as exc:
            raise _error(422, "invalid_query", str(exc)) from exc
        return SearchResponse(**result.__dict__)

    def _material_and_cif(material_id: str) -> tuple[dict, str]:
        with repository() as repo:
            material = repo.get(material_id)
            cif = repo.read_cif(material_id) if material is not None else None
        if material is None or cif is None:
            raise _error(404, "material_not_found", f"Unknown material: {material_id}")
        material.pop("blob_offset", None)
        material.pop("blob_length", None)
        return material, cif

    @app.get("/api/materials/{material_id}")
    async def material_detail(material_id: str):
        material, _ = _material_and_cif(material_id)
        return material

    @app.get("/api/materials/{material_id}/structure")
    async def material_structure(material_id: str):
        _, cif = _material_and_cif(material_id)
        try:
            return parse_cif_structure(cif)
        except StructureParseError as exc:
            raise _error(422, "structure_parse_failed", str(exc)) from exc

    @app.get("/api/materials/{material_id}/cif")
    async def material_cif(material_id: str):
        _, cif = _material_and_cif(material_id)
        return Response(
            content=cif,
            media_type="chemical/x-cif",
            headers={"Content-Disposition": f'attachment; filename="{material_id}.cif"'},
        )

    @app.get("/api/materials/{material_id}/render")
    async def material_render(
        material_id: str,
        view: Literal["isometric", "front", "top"] = "isometric",
        representation: Literal["ball_stick", "spacefill"] = "ball_stick",
        supercell: str = "2,2,2",
        show_cell: bool = True,
        quality: Literal["preview", "high"] = "preview",
    ):
        _, cif = _material_and_cif(material_id)
        try:
            repeats = tuple(int(value.strip()) for value in supercell.split(","))
            options = RenderOptions(
                view=view,
                representation=representation,
                supercell=repeats,
                show_cell=show_cell,
                quality=quality,
            )
            path = await render_service.render_async(cif, material_id, options)
        except (TypeError, ValueError) as exc:
            raise _error(422, "invalid_render_options", str(exc)) from exc
        except OvitoRenderError as exc:
            raise _error(503, "ovito_render_failed", str(exc)) from exc
        return Response(
            content=path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    frontend_path = Path(frontend_dir) if frontend_dir else None
    if frontend_path and (frontend_path / "index.html").is_file():
        assets = frontend_path / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{route:path}", include_in_schema=False)
        async def frontend(route: str):
            requested = frontend_path / route
            if requested.is_file() and frontend_path in requested.resolve().parents:
                return FileResponse(requested)
            return HTMLResponse((frontend_path / "index.html").read_text(encoding="utf-8"))

    return app
