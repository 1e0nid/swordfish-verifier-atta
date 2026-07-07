import logging
import httpx
from typing import Any, Dict, Optional
from src.config import EmulatorConfig


logger = logging.getLogger("Swordfish-client")

class SwordfishHttpClient:
    def __init__(self, config: EmulatorConfig):
        self.base_url = str(config.url).rstrip("/")
        self.timeout = config.timeout
        self.username = config.username
        self.password = config.password

        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "OData-Version": "4.0",
        }
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        auth = None

        if self.username and self.password:
            auth = httpx.AsyncAuth(httpx.BasicAuth(self.username, self.password))

        self.client = httpx.AsyncClient(
            base_url = self.base_url,
            headers = self.headers,
            auth=auth,
            timeout=float(self.timeout),
            follow_redirects=True
        )

        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.client:
            await self.client.aclose()
    
    async def send_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        
        if not self.client:
            raise RuntimeError("Client doesn't init")
        
        endpoint_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"

        try:
            response = await self.client.request(
                method = method.upper(),
                url=endpoint_path,
                json=json_data,
            )

            try:
                response_json = response.json()
            except ValueError:
                response_json = {"_raw_text": response.text}

            return {
                "success": response.is_success,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "data": response_json,
                "error_message": None
            }

        except httpx.TimeoutException:
            logger.warning(f"Таймаут запроса [{method}] к эндпоинту {endpoint_path}")
            return {
                "success": False,
                "status_code": 408,
                "headers": {},
                "data": {},
                "error_message": f"Превышено время ожидания (Timeout: {self.timeout}s)"
            }
            
        except httpx.ConnectError:
            logger.error(f"Ошибка подключения к эмулятору по пути: {self.base_url}{endpoint_path}")
            return {
                "success": False,
                "status_code": 503,
                "headers": {},
                "data": {},
                "error_message": "Не удалось установить соединение с сервером эмулятора"
            }
            
        except Exception as e:
            logger.error(f"Непредвиденная ошибка сети: {str(e)}")
            return {
                "success": False,
                "status_code": 500,
                "headers": {},
                "data": {},
                "error_message": f"Внутренняя ошибка верификатора при отправке запроса: {str(e)}"
            }