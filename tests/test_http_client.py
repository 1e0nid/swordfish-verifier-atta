import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock
from src.client.http_client import SwordfishHttpClient


# --- МОК КОНФИГУРАЦИИ ---
class MockConfig:
    def __init__(self):
        self.url = "http://mock-storage.local/redfish/v1"
        self.timeout = 5
        self.username = "admin"
        self.password = "password123"


# --- ТЕСТЫ ---

@pytest.mark.asyncio
async def test_client_context_manager_and_init(mocker):
    """Проверка корректной инициализации и закрытия асинхронного клиента"""
    config = MockConfig()
    config.username = None  # Отключаем авто-аутентификацию для этого теста

    mock_async_client = MagicMock()
    mock_async_client.aclose = AsyncMock()
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    async with SwordfishHttpClient(config) as client:
        assert client.base_url == "http://mock-storage.local/redfish/v1"
        assert client.client == mock_async_client

    mock_async_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_success_via_header():
    """Успешный перехват X-Auth-Token из заголовков ответа СХД"""
    config = MockConfig()
    client = SwordfishHttpClient(config)

    mock_client_instance = MagicMock()
    # Эмулируем ответ сервера, где токен лежит в Headers
    mock_response = httpx.Response(201, headers={"X-Auth-Token": "secret_token_from_header"})
    mock_client_instance.post = AsyncMock(return_value=mock_response)
    mock_client_instance.headers = {}

    client.client = mock_client_instance
    await client._authenticate()

    # Проверяем мультиформатную подстановку
    assert client.client.headers["X-Auth-Token"] == "secret_token_from_header"
    assert client.client.headers["Authorization"] == "Bearer secret_token_from_header"


@pytest.mark.asyncio
async def test_authenticate_success_via_json_body():
    """Успешный перехват SessionToken из JSON-тела ответа"""
    config = MockConfig()
    client = SwordfishHttpClient(config)

    mock_client_instance = MagicMock()
    # Сервер вернул токен внутри JSON структуры
    mock_response = httpx.Response(200, json={"SessionToken": "secret_token_from_json"})
    mock_client_instance.post = AsyncMock(return_value=mock_response)
    mock_client_instance.headers = {}

    client.client = mock_client_instance
    await client._authenticate()

    assert client.client.headers["x-auth-token"] == "secret_token_from_json"


@pytest.mark.asyncio
async def test_authenticate_fallback_to_basic_auth_on_error():
    """Если токен не найден или код ответа плохой — включается BasicAuth"""
    config = MockConfig()
    client = SwordfishHttpClient(config)

    mock_client_instance = MagicMock()
    mock_response = httpx.Response(400, json={"error": "Bad Request"})
    mock_client_instance.post = AsyncMock(return_value=mock_response)

    client.client = mock_client_instance
    await client._authenticate()

    # Проверяем, что клиент переключился на стандартную базовую авторизацию
    assert isinstance(client.client.auth, httpx.BasicAuth)


@pytest.mark.asyncio
async def test_authenticate_exception_handling():
    """Если при запросе токена произошел сетевой сбой — клиент безопасно откатывается на BasicAuth"""
    config = MockConfig()
    client = SwordfishHttpClient(config)

    mock_client_instance = MagicMock()
    # Имитируем жесткое падение сети во время запроса авторизации
    mock_client_instance.post = AsyncMock(side_effect=httpx.ConnectError("Network dead"))

    client.client = mock_client_instance
    await client._authenticate()

    assert isinstance(client.client.auth, httpx.BasicAuth)


@pytest.mark.asyncio
async def test_send_request_success_json():
    """Проверка успешного выполнения запроса и парсинга валидного JSON"""
    config = MockConfig()
    client = SwordfishHttpClient(config)

    mock_client_instance = MagicMock()
    mock_response = httpx.Response(200, json={"status": "All systems operational"})
    mock_client_instance.request = AsyncMock(return_value=mock_response)
    client.client = mock_client_instance

    result = await client.send_request("GET", "Chassis")

    assert result["success"] is True
    assert result["status_code"] == 200
    assert result["data"] == {"status": "All systems operational"}


@pytest.mark.asyncio
async def test_send_request_invalid_json_fallback():
    """Если сервер вернул не JSON (например HTML/текст), он сохраняется в _raw_text"""
    config = MockConfig()
    client = SwordfishHttpClient(config)

    mock_client_instance = MagicMock()
    mock_response = httpx.Response(200, text="Plain text response")
    mock_client_instance.request = AsyncMock(return_value=mock_response)
    client.client = mock_client_instance

    result = await client.send_request("POST", "/Volumes", json_data={"test": 1})
    assert result["data"] == {"_raw_text": "Plain text response"}


@pytest.mark.asyncio
async def test_send_request_401_diagnostic_logging(mocker):
    """Проверка вызова расширенной диагностики при ошибке 401 Unauthorized"""
    config = MockConfig()
    client = SwordfishHttpClient(config)

    mock_client_instance = MagicMock()
    # Для 401 логирования нужен объект запроса внутри ответа
    mock_req = httpx.Request("GET", "http://mock-storage.local/redfish/v1/Chassis")
    mock_response = httpx.Response(401, json={"detail": "Invalid token"}, request=mock_req)
    mock_client_instance.request = AsyncMock(return_value=mock_response)
    client.client = mock_client_instance

    # Мокаем логгер, чтобы проверить, что ошибка зафиксирована
    mock_logger = mocker.patch("src.client.http_client.logger.error")

    result = await client.send_request("GET", "/Chassis")

    assert result["status_code"] == 401
    mock_logger.assert_called_once()


@pytest.mark.asyncio
async def test_send_request_network_exceptions():
    """Проверка перехвата таймаутов, ошибок подключения и непредвиденных исключений"""
    config = MockConfig()
    client = SwordfishHttpClient(config)
    mock_client_instance = MagicMock()
    client.client = mock_client_instance

    # 1. Тестируем Timeout -> Код 408
    mock_client_instance.request = AsyncMock(side_effect=httpx.TimeoutException("Timeout out"))
    res_timeout = await client.send_request("GET", "/Volumes")
    assert res_timeout["status_code"] == 408
    assert res_timeout["error_message"] == "Timeout"

    # 2. Тестируем ConnectError -> Код 503
    mock_client_instance.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    res_connect = await client.send_request("GET", "/Volumes")
    assert res_connect["status_code"] == 503
    assert res_connect["error_message"] == "ConnectError"

    # 3. Тестируем критический сбой (Exception) -> Код 500
    mock_client_instance.request = AsyncMock(side_effect=RuntimeError("System crash"))
    res_crash = await client.send_request("GET", "/Volumes")
    assert res_crash["status_code"] == 500
    assert "System crash" in res_crash["error_message"]


@pytest.mark.asyncio
async def test_send_request_uninitialized():
    """Попытка отправить запрос через неинициализированный клиент вызывает RuntimeError"""
    config = MockConfig()
    client = SwordfishHttpClient(config)
    # client.client равен None

    with pytest.raises(RuntimeError, match="Клиент не инициализирован."):
        await client.send_request("GET", "/Volumes")