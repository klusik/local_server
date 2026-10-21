"""Windows-only credential storage and owner-only temporary directory ACLs."""

from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes as w
from pathlib import Path


class _Credential(ctypes.Structure):
    _fields_ = [("Flags", w.DWORD), ("Type", w.DWORD), ("TargetName", w.LPWSTR),
                ("Comment", w.LPWSTR), ("LastWritten", w.FILETIME),
                ("CredentialBlobSize", w.DWORD), ("CredentialBlob", ctypes.c_void_p),
                ("Persist", w.DWORD), ("AttributeCount", w.DWORD),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", w.LPWSTR),
                ("UserName", w.LPWSTR)]


def _apis() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    if os.name != "nt":
        raise RuntimeError("MySQL secrets require Windows Credential Manager")
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.DWORD)]
    adv.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.c_void_p]
    adv.CredWriteW.argtypes = [ctypes.POINTER(_Credential), w.DWORD]
    adv.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(_Credential))]
    adv.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
    adv.CredFree.argtypes = [ctypes.c_void_p]
    return adv, kernel


def restrict_directory(directory: Path) -> None:
    """Set a protected inheritable DACL before writing any sensitive bytes.

    Only the current user and SYSTEM get access. Filesystems without Windows
    ACL support fail closed. This is access control, not guaranteed disk erasure.
    """
    adv, kernel = _apis()
    token = w.HANDLE()
    sid_text = w.LPWSTR()
    descriptor = ctypes.c_void_p()
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError("Cannot read Windows identity")
        size = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not adv.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise OSError("Cannot read Windows user SID")
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not adv.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise OSError("Cannot encode Windows user SID")
        sddl = f"D:P(A;OICI;FA;;;{sid_text.value})(A;OICI;FA;;;SY)"
        if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise OSError("Cannot construct private storage ACL")
        if not adv.SetFileSecurityW(str(directory), 0x80000004, descriptor):
            raise OSError("Cannot protect MySQL storage; a Windows ACL filesystem is required")
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


class WindowsCredentialStore:
    """Keep passwords in the current Windows user's local credential vault."""

    @staticmethod
    def _target(reference: str) -> str:
        import uuid
        return "LocalServer/MySQL/" + str(uuid.UUID(reference))

    def put(self, reference: str, passwords: dict[str, str]) -> None:
        """Persist generated secrets without serializing them into project state."""
        adv, _ = _apis()
        data = json.dumps(passwords).encode("utf-8")
        buffer = ctypes.create_string_buffer(data)
        credential = _Credential(Type=1, TargetName=self._target(reference),
                                 CredentialBlobSize=len(data),
                                 CredentialBlob=ctypes.cast(buffer, ctypes.c_void_p),
                                 Persist=2, UserName="Local Server MySQL")
        try:
            if not adv.CredWriteW(ctypes.byref(credential), 0):
                raise RuntimeError("Windows Credential Manager could not save MySQL credentials")
        finally:
            ctypes.memset(buffer, 0, len(buffer))

    def get(self, reference: str) -> dict[str, str]:
        """Refuse missing credentials after account/computer changes; never reset data."""
        adv, _ = _apis()
        pointer = ctypes.POINTER(_Credential)()
        if not adv.CredReadW(self._target(reference), 1, 0, ctypes.byref(pointer)):
            raise RuntimeError("MySQL credentials are unavailable for this Windows user/computer. "
                               "Return to the original account/computer or restore its credentials; "
                               "database files are preserved and passwords will not be reset.")
        try:
            result = json.loads(ctypes.string_at(pointer.contents.CredentialBlob,
                                                 pointer.contents.CredentialBlobSize))
            if (not isinstance(result, dict) or not result
                    or any(not isinstance(value, str) or len(value) < 32 for value in result.values())):
                raise RuntimeError("Stored MySQL credentials are invalid; database files are preserved")
            return result
        finally:
            adv.CredFree(pointer)

    def delete(self, reference: str) -> None:
        """Remove only credentials owned by a discarded first initialization."""
        adv, _ = _apis()
        if not adv.CredDeleteW(self._target(reference), 1, 0) and ctypes.get_last_error() != 1168:
            raise RuntimeError("Cannot remove discarded MySQL credentials")
