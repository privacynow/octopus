"""Startup-built authority/admin_interface directory for control-plane routing."""

from __future__ import annotations


class ControlPlaneDirectory:
    def __init__(self) -> None:
        self._by_admin_interface: dict[str, set[str]] = {}

    def register(self, *, admin_interface: str, implementation_ref: str) -> None:
        self._by_admin_interface.setdefault(admin_interface, set()).add(implementation_ref)

    def implementations_for_admin_interface(self, admin_interface: str) -> set[str]:
        return set(self._by_admin_interface.get(admin_interface, set()))

    def admin_interfaces_for_implementation(self, implementation_ref: str) -> set[str]:
        admin_interfaces: set[str] = set()
        for admin_interface, authorities in self._by_admin_interface.items():
            if implementation_ref in authorities:
                admin_interfaces.add(admin_interface)
        return admin_interfaces

    def all_admin_interfaces(self) -> set[str]:
        return set(self._by_admin_interface.keys())

    def all_implementations(self) -> set[str]:
        authorities: set[str] = set()
        for refs in self._by_admin_interface.values():
            authorities.update(refs)
        return authorities

    def all_pairs(self) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for admin_interface, authorities in self._by_admin_interface.items():
            for implementation_ref in authorities:
                pairs.add((implementation_ref, admin_interface))
        return pairs


def build_control_plane_directory(
    implemented_admin_interfaces: dict[str, set[str]],
) -> ControlPlaneDirectory:
    directory = ControlPlaneDirectory()
    for implementation_ref, admin_interfaces in implemented_admin_interfaces.items():
        for admin_interface in admin_interfaces:
            directory.register(admin_interface=admin_interface, implementation_ref=implementation_ref)
    return directory
