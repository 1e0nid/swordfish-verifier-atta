import pytest
from unittest.mock import AsyncMock, MagicMock
from src.verifier.discovery import SwordfishDiscoverer


def test_infer_resource_name():
    """Проверка эвристического определения имени ресурса по URL"""
    discoverer = SwordfishDiscoverer(MagicMock())

    assert discoverer._infer_resource_name("/redfish/v1/StorageServices/1") == "StorageService"
    assert discoverer._infer_resource_name("/redfish/v1/Chassis/Rack1") == "Chassis"
    assert discoverer._infer_resource_name("/redfish/v1/Volumes") == "Volume"
    assert discoverer._infer_resource_name("/redfish/v1/UnknownPath") == "ServiceRoot"


@pytest.mark.asyncio
async def test_crawl_success_with_odata_type():
    """Успешный обход эндпоинта с явным указанием @odata.type"""
    mock_client = MagicMock()
    # Эмулируем успешный ответ от корня API
    mock_client.send_request = AsyncMock(return_value={
        "success": True,
        "data": {
            "@odata.type": "#ChassisCollection.ChassisCollection",
            "@odata.id": "/redfish/v1/Chassis",
            "Members": [
                {"@odata.id": "/redfish/v1/Chassis/Slot1"}
            ]
        }
    })

    discoverer = SwordfishDiscoverer(mock_client)

    # Чтобы тест не ушёл в бесконечный рекурсивный обход Slot1,
    # добавим дочернюю ссылку в visited_urls заранее
    discoverer.visited_urls.add("/redfish/v1/Chassis/Slot1")

    await discoverer._crawl("/redfish/v1/Chassis")

    # Проверяем, что тип ресурса распарсился из @odata.type (всё, что после точки)
    assert "ChassisCollection" in discoverer.discovered_endpoints
    assert "/redfish/v1/Chassis" in discoverer.discovered_endpoints["ChassisCollection"]


@pytest.mark.asyncio
async def test_crawl_failed_endpoint_still_saved():
    """Если сервер вернул 401/404, эндпоинт всё равно сохраняется на базе эвристики"""
    mock_client = MagicMock()
    # Имитируем ошибку доступа (например, СХД требует авторизации)
    mock_client.send_request = AsyncMock(return_value={
        "success": False,
        "data": None
    })

    discoverer = SwordfishDiscoverer(mock_client)
    await discoverer._crawl("/redfish/v1/StoragePools/Pool-A")

    # Проверяем, что имя определилось по урлу, а сам эндпоинт попал в выборку
    assert "StoragePool" in discoverer.discovered_endpoints
    assert "/redfish/v1/StoragePools/Pool-A" in discoverer.discovered_endpoints["StoragePool"]


@pytest.mark.asyncio
async def test_crawl_deduplication():
    """Проверка защиты от зацикливания: посещённые URL не запрашиваются повторно"""
    mock_client = MagicMock()
    mock_client.send_request = AsyncMock()

    discoverer = SwordfishDiscoverer(mock_client)
    # Помечаем урл как уже посещённый
    discoverer.visited_urls.add("/redfish/v1/Volumes/1")

    await discoverer._crawl("/redfish/v1/Volumes/1")

    # Клиент не должен вызываться, так как урл в черном списке
    mock_client.send_request.assert_not_called()


@pytest.mark.asyncio
async def test_extract_links_recursion():
    """Проверка глубокого извлечения ссылок из списков и вложенных словарей"""
    mock_client = MagicMock()
    discoverer = SwordfishDiscoverer(mock_client)

    # Мокаем метод _crawl, чтобы просто смотреть, какие ссылки он пытается вызвать
    discoverer._crawl = AsyncMock()

    # Сложная структура ответа с вложенными листами и метаданными
    complex_data = {
        "Storage": {
            "@odata.id": "/redfish/v1/Storage/1",
            "Drives": [
                {"@odata.id": "/redfish/v1/Drives/Drive0"},
                {"@odata.id": "/redfish/v1/Drives/Drive1"}
            ]
        },
        "@some_ignored_metadata": {
            "@odata.id": "/redfish/v1/ShouldIgnoreThis"
        }
    }

    await discoverer._extract_links(complex_data)

    # Проверяем, что краулер нашёл все валидные ссылки и проигнорировал служебные @-поля
    called_urls = [call.args[0] for call in discoverer._crawl.call_args_list]
    assert "/redfish/v1/Storage/1" in called_urls
    assert "/redfish/v1/Drives/Drive0" in called_urls
    assert "/redfish/v1/Drives/Drive1" in called_urls
    assert "/redfish/v1/ShouldIgnoreThis" not in called_urls


@pytest.mark.asyncio
async def test_full_discover_workflow():
    """Интеграционный тест полного цикла обхода от корня API"""
    mock_client = MagicMock()

    # ИСПОЛЬЗУЕМ AsyncMock вместо обычного side_effect у MagicMock
    mock_client.send_request = AsyncMock(side_effect=[
        # Первый вызов (Ответ на /redfish/v1)
        {
            "success": True,
            "data": {
                "@odata.type": "#ServiceRoot.ServiceRoot",
                "Systems": {"@odata.id": "/redfish/v1/Systems"}
            }
        },
        # Второй вызов (Ответ на /redfish/v1/Systems)
        {
            "success": True,
            "data": {
                "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection"
            }
        }
    ])

    discoverer = SwordfishDiscoverer(mock_client)
    endpoints = await discoverer.discover()

    # Проверки
    assert "ServiceRoot" in endpoints
    assert "ComputerSystemCollection" in endpoints
    assert "/redfish/v1/Systems" in endpoints["ComputerSystemCollection"]