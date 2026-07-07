import logging
import httpx
from typing import Any, Dict, Optional
from src.config import EmulatorConfig

logger = logging.getLogger("swordfish_client")

class SwordfishHttpClient:
    """
    Асинхронный HTTP-клиент с поддержкой полноценной сессионной авторизации Redfish/Swordfish (X-Auth-Token).
    """
    def __init__(self, config: EmulatorConfig):
        self.base_url = str(config.url).rstrip("/")
        self.timeout = config.timeout
        self.username = config.username
        self.password = config.password
        
        # Стандартные заголовки для работы с Redfish/Swordfish API
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "OData-Version": "4.0"
        }
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Открытие асинхронного сессионного клиента и прохождение авторизации."""
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=float(self.timeout),
            follow_redirects=True
        )
        
        # Если в config.yml переданы логин и пароль, включаем гибридную защиту
        if self.username and self.password:
            await self._authenticate()
            
        return self

    async def _authenticate(self):
        """
        Выполняет комбинированную аутентификацию.
        Включает Basic Auth и параллельно запрашивает сессионный X-Auth-Token.
        """
        logger.info("Применение гибридной авторизации (Basic Auth + X-Auth-Token)...")
        
        # 1. СРАЗУ жестко включаем Basic Auth как гарантированный метод для всех запросов
        self.client.auth = httpx.BasicAuth(self.username, self.password)
        
        # 2. Пытаемся параллельно получить сессионный токен по стандарту Redfish/Swordfish
        session_payload = {
            "UserName": self.username,
            "Password": self.password
        }
        
        try:
            response = await self.client.post("/redfish/v1/SessionService/Sessions", json=session_payload)
            
            if response.status_code in [200, 201]:
                token = response.headers.get("X-Auth-Token")
                if token:
                    # Добавляем токен в заголовки. Теперь клиент шлет И Basic Auth, И X-Auth-Token!
                    self.client.headers["X-Auth-Token"] = token
                    logger.info("Сессионный токен X-Auth-Token успешно добавлен к заголовкам запросов.")
                    return
                
                # Дополнительный хак для некоторых самописных эмуляторов: поиск токена в теле JSON
                try:
                    data = response.json()
                    if isinstance(data, dict) and "Token" in data:
                        self.client.headers["X-Auth-Token"] = data["Token"]
                        logger.info("Токен извлечен из тела JSON-ответа и добавлен к заголовкам.")
                except ValueError:
                    pass
                    
        except Exception as e:
            logger.warning(f"Не удалось выполнить Redfish Session Auth ({e}), продолжаем работу исключи")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрытие сессии при выходе из контекста."""
        if self.client:
            await self.client.aclose()

    async def send_request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("Клиент не инициализирован. Используйте 'async with'.")

        endpoint_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        
        try:
            response = await self.client.request(
                method=method.upper(),
                url=endpoint_path,
                json=json_data
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