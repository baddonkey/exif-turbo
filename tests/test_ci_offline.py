import os
import socket

import pytest


@pytest.mark.skipif(os.environ.get("EXIF_TURBO_TEST_OFFLINE") != "1", reason="CI offline mode only")
def test_ci_offline_socket_connection_is_rejected_before_network_access() -> None:
    # Arrange
    connection = socket.socket()

    # Act / Assert
    try:
        with pytest.raises(RuntimeError, match="must mock network/model downloads"):
            connection.connect(("192.0.2.1", 443))
    finally:
        connection.close()