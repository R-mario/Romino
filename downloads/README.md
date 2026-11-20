# Directorio de Staging (`downloads/`)

Coloca aquí los binarios descargados antes de ejecutar `scripts/pc_flash_oneplus2.sh`. Este directorio ignora archivos `.img`, `.zip` y `.apk` en Git.

## Archivos necesarios

| Archivo esperado (patrón) | Obligatorio | Fuente oficial verificada |
| :--- | :---: | :--- |
| `twrp-*oneplus2*.img` | Sí | [dl.twrp.me/oneplus2/](https://dl.twrp.me/oneplus2/) |
| `lineage-*oneplus2*.zip` | Sí | [XDA LineageOS 17.1 (Android 10 Oficial)](https://forum.xda-developers.com/t/rom-official-lineageos-17-1-for-oneplus2-android-10.3990807/) o [XDA LineageOS 20.0 (Android 13 Estable)](https://forum.xda-developers.com/t/rom-t-lineageos-20-0-for-oneplus-2-android-13-stable-unofficial-signature-spoofing.4539169/) |
| `termux-app_*arm64-v8a*.apk` | Sí | [github.com/termux/termux-app/releases](https://github.com/termux/termux-app/releases) |
| `termux-boot-app_*.apk` | Sí | [github.com/termux/termux-boot/releases](https://github.com/termux/termux-boot/releases) |
| `termux-api-app_*.apk` | Sí | [github.com/termux/termux-api/releases](https://github.com/termux/termux-api/releases) |
| `Magisk-*.zip` | Opcional | [github.com/topjohnwu/Magisk/releases](https://github.com/topjohnwu/Magisk/releases) *(renombrar `.apk` a `.zip` para sideload si deseas root + ACC)* |

> **Importante:** Las tres APKs de Termux (`termux-app`, `termux-boot`, `termux-api`) deben descargarse de la **misma fuente** (todas desde GitHub Releases o todas desde F-Droid) para que coincidan sus firmas criptográficas.

## Comprobación automática
Desde la raíz del repositorio:
```bash
bash scripts/pc_check_prereqs.sh
```
