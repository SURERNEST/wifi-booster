# ⚡ Optimizador de Internet PRO 9.1

**Una aplicación de escritorio moderna para Windows que mejora tu conexión a Internet con inteligencia, modos especiales y un diseño profesional.**

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge\&logo=python)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![CustomTkinter](https://img.shields.io/badge/UI-customtkinter-blueviolet?style=for-the-badge)

---

## 🎯 Funcionalidades Principales

✅ **Optimización en un clic**
✅ **Test de velocidad con recomendaciones inteligentes**
✅ **Cambio automático de DNS (Cloudflare, Google, OpenDNS)**
✅ **Modo Juego**: Prioriza latencia baja
✅ **Modo Ahorro**: Reduce uso de red para conexiones lentas
✅ **Limpiar caché DNS, reiniciar adaptador de red**
✅ **IP pública/local visible**
✅ **Interfaz profesional responsiva y oscura**
✅ **Pantalla completa adaptable a resolución**
✅ **Scroll automático para pantallas pequeñas**
✅ **Registro automático de acciones en log**



## 📦 Instalación

### 1. Clona este repositorio

```bash
git clone https://github.com/tuusuario/optimizador-internet-pro.git
cd optimizador-internet-pro
```

### 2. Instala las dependencias

```bash
pip install customtkinter speedtest-cli requests
```

### 3. Ejecuta el programa

```bash
python main.py
```

---

## 🧠 ¿Cómo funciona?

Este optimizador utiliza comandos internos de red (`netsh`, `ipconfig`) y bibliotecas Python para mejorar el rendimiento general de tu conexión:

* Cambia los DNS automáticamente.
* Realiza un test de velocidad con `speedtest`.
* Ofrece recomendaciones personalizadas basadas en tu conexión real.
* Ejecuta acciones útiles como reiniciar adaptador o limpiar caché DNS.

---

## 🚀 Modos Inteligentes

### 🎮 Modo Juego

* Aplica DNS Cloudflare.
* Limpia caché DNS.
* Recomienda cerrar apps como Discord, Steam, etc.

### 💡 Modo Ahorro

* Aplica DNS Google.
* Sugerencias para reducir consumo de red (ideal para datos móviles o conexiones lentas).

---

## 💻 Requisitos

* Windows 10 u 11
* Python 3.10 o superior
* Acceso de administrador para cambios de red

---

## 📜 Licencia

Este proyecto está bajo la licencia [MIT](LICENSE).

---

## 👨‍💻 Autor

Desarrollado por **Boris Andres**
💡 Optimizado con `Python + customtkinter`
