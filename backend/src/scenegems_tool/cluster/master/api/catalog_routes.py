"""The operator's catalog routes: what a campaign may run (P5.1).

They are read-only and need no database, so the master mounts them whether or not it has the
campaign stores. Like the other operator routes they have no authentication yet.

    GET CATALOG_PATH/classes?folder=&pattern=&limit=&offset=   the class catalog's classes in catalog order: id, folder, vessel and
                                           obstacle counts, content hash. folder is a catalog folder, pattern a scope pattern (a folder
                                           pattern without a slash, a class id pattern with one); both narrow the list. The number of
                                           matching classes is in X-Total-Count. 503 when the master has no catalog folder
    GET CATALOG_PATH/stacks                the stack options a campaign config accepts with their repeatability tier and parameters,
                                           the monitors, the trajectory generators with their parameter keys and defaults, the run
                                           fields, and the resolver's other stacks with the reasons a campaign cannot use them
                                           (catalog_views.py describes the shape)
"""

from typing import Optional

import anyio
from fastapi import APIRouter, HTTPException, Response

from scenegems_tool.cluster.master.api.catalog_views import class_view, stacks_view
from scenegems_tool.cluster.protocol.routes import CATALOG_PATH

MAX_LISTED = 1000


def catalog_router() -> APIRouter:
    router = APIRouter()

    def classes(folder: Optional[str], pattern: Optional[str]) -> list:
        # Imported here: the catalog module is part of the campaign package, whose config model the master keeps out of its startup
        from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog

        catalog = ClassCatalog.default()
        found = catalog.classes() if not pattern else catalog.expand(pattern)
        return [scenario_class for scenario_class in found if folder is None or scenario_class.folder == folder]

    @router.get(CATALOG_PATH + "/classes")
    async def list_classes(response: Response, folder: Optional[str] = None, pattern: Optional[str] = None, limit: int = 100, offset: int = 0) -> list:
        try:
            found = await anyio.to_thread.run_sync(classes, folder, pattern)
        except FileNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error))
        response.headers["X-Total-Count"] = str(len(found))
        start = max(0, offset)
        return [class_view(scenario_class) for scenario_class in found[start : start + max(1, min(limit, MAX_LISTED))]]

    @router.get(CATALOG_PATH + "/stacks")
    async def list_stacks() -> dict:
        return await anyio.to_thread.run_sync(stacks_view)

    return router
