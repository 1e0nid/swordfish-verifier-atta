import logging
from typing import Dict, List, Set, Any
from src.client.http_client import SwordfishHttpClient

logger = logging.getLogger("swordfish_discovery")

class SwordfishDiscoverer:
    """
    Автоматический краулер API СХД. Собирает все ручки, включая упавшие (401/404),
    чтобы зафиксировать их дефекты в финальном отчете.
    """
    def __init__(self, client: SwordfishHttpClient):
        self.client = client
        self.discovered_endpoints: Dict[str, List[str]] = {}
        self.visited_urls: Set[str] = set()

    def _infer_resource_name(self, url: str) -> str:
        """
        Вспомогательный метод: определяет тип ресурса по URL, 
        если сервер заблокировал доступ (401) или скрыл его (404).
        """
        url_lower = url.lower()
        if "storageservices" in url_lower:
            return "StorageService"
        if "storagepools" in url_lower:
            return "StoragePool"
        if "volumes" in url_lower:
            return "Volume"
        if "drives" in url_lower:
            return "Drive"
        if "systems" in url_lower:
            return "Systems"
        if "chassis" in url_lower:
            return "Chassis"
        if "fabrics" in url_lower:
            return "Fabric"
        if "managers" in url_lower:
            return "Manager"
        return "ServiceRoot"

    async def discover(self) -> Dict[str, List[str]]:
        logger.info("Запуск динамического обнаружения эндпоинтов СХД...")
        self.discovered_endpoints = {}
        self.visited_urls = set()
        
        # Обходим корень API
        await self._crawl("/redfish/v1")
        if not self.discovered_endpoints:
            await self._crawl("/redfish/v1/")
            
        return self.discovered_endpoints

    async def _crawl(self, url: str):
        if url in self.visited_urls:
            return
        self.visited_urls.add(url)

        response = await self.client.send_request("GET", url)
        
        # Если эндпоинт вернул 401 или 404, мы ВСЕ РАВНО добавляем его,
        # чтобы валидатор зафиксировал FAIL в отчете по требованиям ТЗ!
        if not response["success"]:
            res_name = self._infer_resource_name(url)
            if res_name not in self.discovered_endpoints:
                self.discovered_endpoints[res_name] = []
            if url not in self.discovered_endpoints[res_name]:
                self.discovered_endpoints[res_name].append(url)
            return

        data = response["data"]
        if not isinstance(data, dict):
            return
        
        # Пытаемся вытащить имя из системного типа @odata.type
        odata_type = data.get("@odata.type", "")
        if odata_type and "." in odata_type:
            res_name = odata_type.split(".")[-1]
        else:
            res_name = self._infer_resource_name(url)

        if res_name not in self.discovered_endpoints:
            self.discovered_endpoints[res_name] = []
        if url not in self.discovered_endpoints[res_name]:
            self.discovered_endpoints[res_name].append(url)

        # Рекурсивно собираем дочерние ссылки, даже если текущий узел пустой
        await self._extract_links(data)

    async def _extract_links(self, data: Any):
        if isinstance(data, dict):
            if "@odata.id" in data and isinstance(data["@odata.id"], str):
                path = data["@odata.id"]
                if path.startswith("/redfish/v1"):
                    await self._crawl(path)
            for key, value in data.items():
                if key.startswith("@") and key != "@odata.id":
                    continue
                await self._extract_links(value)
        elif isinstance(data, list):
            for item in data:
                await self._extract_links(item)