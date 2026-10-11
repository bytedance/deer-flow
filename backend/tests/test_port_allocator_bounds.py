"""Port searches must stop at the largest valid TCP port."""

from unittest.mock import patch

import pytest

from deerflow.utils.network import PortAllocator


@pytest.mark.parametrize("start_port", [65534, 65535])
def test_reserved_tail_reports_exhaustion(start_port):
    allocator = PortAllocator()
    allocator._reserved_ports.update(range(start_port, 65536))

    with pytest.raises(RuntimeError, match="No available port"):
        allocator.allocate(start_port=start_port)


def test_occupied_tail_never_probes_invalid_port():
    allocator = PortAllocator()

    def bind(address):
        if address[1] > 65535:
            raise OverflowError("port must be 0-65535")
        raise OSError("Address already in use")

    with patch("deerflow.utils.network.socket.socket") as socket_factory:
        sock = socket_factory.return_value.__enter__.return_value
        sock.bind.side_effect = bind
        with pytest.raises(RuntimeError, match="No available port"):
            allocator.allocate(start_port=65535)
        sock.bind.assert_called_once_with(("0.0.0.0", 65535))
    assert not allocator._reserved_ports


def test_last_valid_port_can_be_allocated_and_released():
    allocator = PortAllocator()
    allocator._reserved_ports.add(65534)

    with patch("deerflow.utils.network.socket.socket") as socket_factory:
        sock = socket_factory.return_value.__enter__.return_value
        with allocator.allocate_context(start_port=65534) as port:
            assert port == 65535
            assert port in allocator._reserved_ports
            sock.bind.assert_called_once_with(("0.0.0.0", 65535))
        assert port not in allocator._reserved_ports
    assert allocator._reserved_ports == {65534}


def test_search_still_respects_max_range():
    allocator = PortAllocator()
    allocator._reserved_ports.update({8080, 8081})

    with patch.object(allocator, "_is_port_available", return_value=False) as probe:
        with pytest.raises(RuntimeError, match="No available port"):
            allocator.allocate(start_port=8080, max_range=2)
        assert [call.args[0] for call in probe.call_args_list] == [8080, 8081]
