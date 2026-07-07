import logging
import httpx
from typing import Any, Dict, Optional

logger = logging.getLogger("swordfish_client")

class SwordfishHttpClient:
    """
    Адаптивный асинхронный HTTP-клиент с расширенным логированием 
    и мультиформатной отправкой токенов авторизации.
    """
    def __init__(self, config):
        self.base_url = str(config.url).rstrip("/")
        self.timeout = config.timeout
        self.username = config.username
        self.password = config.password
        
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "OData-Version": "4.0"
        }
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=float(self.timeout),
            follow_redirects=True
        )
        
        if self.username and self.password:
            await self._authenticate()
            
        return self

    async def _authenticate(self):
        logger.info("Запрос сессионного токена у эмулятора СХД...")
        session_payload = {"UserName": self.username, "Password": self.password}
        
        try:
            response = await self.client.post("/redfish/v1/SessionService/Sessions", json=session_payload)
            
            if response.status_code in [200, 201]:
                # Ищем токен в заголовках ответа (без учета регистра)
                token = None
                for header_key, header_val in response.headers.items():
                    if header_key.lower() == "x-auth-token":
                        token = header_val
                        break
                
                if token:
                    logger.info(f"Успешно получен токен авторизации: {token[:8]}...")
                    
                    # МУЛЬТИФОРМАТНАЯ ПОДСТАНОВКА: шлем во всех известных форматах сразу,
                    # чтобы гарантированно удовлетворить любой кастомный эмулятор.
                    self.client.headers["X-Auth-Token"] = token
                    self.client.headers["x-auth-token"] = token
                    self.client.headers["Authorization"] = f"Bearer {token}"
                    return
                
                # Проверяем, может токен пришел внутри JSON тела
                try:
                    data = response.json()
                    for key in ["Token", "token", "SessionToken", "X-Auth-Token"]:
                        if isinstance(data, dict) and key in data:
                            t = data[key]
                            self.client.headers["X-Auth-Token"] = t
                            self.client.headers["x-auth-token"] = t
                            self.client.headers["Authorization"] = f"Bearer {t}"
                            logger.info(f"Токен извлечен из JSON тела: {t[:8]}...")
                            return
                except ValueError:
                    pass

            logger.warning(f"Не удалось извлечь токен (Код: {response.status_code}). Включаю стандартный Basic Auth.")
            self.client.auth = httpx.BasicAuth(self.username, self.password)
            
        except Exception as e:
            logger.error(f"Ошибка при аутентификации: {e}. Откат на Basic Auth.")
            self.client.auth = httpx.BasicAuth(self.username, self.password)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def send_request(self, method: str, endpoint: str, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("Клиент не инициализирован.")

        endpoint_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        
        try:
            # Логируем то, что мы отправляем на сервер для контроля дебага
            logger.debug(f"Запрос: {method.upper()} {endpoint_path}")
            
            response = await self.client.request(method=method.upper(), url=endpoint_path, json=json_data)
            
            try:
                response_json = response.json()
            except ValueError:
                response_json = {"_raw_text": response.text}

            # ДИАГНОСТИКА ОШИБОК: Если сервер ругается на авторизацию (401),
            # мы выводим детальную информацию прямо в консоль логов.
            if response.status_code == 401:
                logger.error(
                    f"Ошибка 401 Unauthorized на эндпоинте {endpoint_path}!\n"
                    f"Отправленные заголовки запроса: {dict(response.request.headers)}\n"
                    f"Ответ сервера (JSON/Текст): {response_json}"
                )

            return {
                "success": response.is_success,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "data": response_json,
                "error_message": None
            }

        except httpx.TimeoutException:
            return {"success": False, "status_code": 408, "headers": {}, "data": {}, "error_message": "Timeout"}
        except httpx.ConnectError:
            return {"success": False, "status_code": 503, "headers": {}, "data": {}, "error_message": "ConnectError"}
        except Exception as e:
            return {"success": False, "status_code": 500, "headers": {}, "data": {}, "error_message": str(e)}