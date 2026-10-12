from exif_turbo.ui.view_models.search_coordinator import SearchCoordinator


def test_search_coordinator_coalesces_active_requests_to_latest_parameters() -> None:
    # Arrange
    coordinator = SearchCoordinator()
    first = coordinator.request({"query": "first"}, show_busy_ui=True,
                                worker_active=False)

    # Act
    queued = coordinator.request({"query": "old"}, show_busy_ui=False,
                                worker_active=True)
    coordinator.request({"query": "latest"}, show_busy_ui=True,
                        worker_active=True)
    resumed = coordinator.take_pending()

    # Assert
    assert first is not None and first.serial == 1
    assert queued is None
    assert resumed is not None
    assert resumed.params == {"query": "latest"}
    assert resumed.show_busy_ui is True
    assert resumed.serial == coordinator.serial == 3


def test_search_coordinator_superseded_serial_is_stale() -> None:
    # Arrange
    coordinator = SearchCoordinator()
    active = coordinator.request({"query": "active"}, show_busy_ui=True,
                                  worker_active=False)
    assert active is not None

    # Act
    coordinator.request({"query": "pending"}, show_busy_ui=False,
                        worker_active=True)
    resumed = coordinator.take_pending()

    # Assert
    assert resumed is not None
    assert not coordinator.is_current(active.serial)
    assert coordinator.is_current(resumed.serial)


def test_search_coordinator_secondary_search_invalidates_pending_result() -> None:
    # Arrange
    coordinator = SearchCoordinator()
    coordinator.request({"query": "normal"}, show_busy_ui=True,
                        worker_active=True)

    # Act
    secondary_serial = coordinator.begin_secondary_search()
    resumed = coordinator.take_pending()

    # Assert
    assert resumed is not None
    assert resumed.serial == secondary_serial
    assert coordinator.is_current(secondary_serial)


def test_search_coordinator_clear_discards_pending_request() -> None:
    # Arrange
    coordinator = SearchCoordinator()
    coordinator.request({"query": "pending"}, show_busy_ui=True,
                        worker_active=True)

    # Act
    coordinator.clear()

    # Assert
    assert coordinator.take_pending() is None