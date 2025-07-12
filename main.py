import os
import time
import threading
import speedtest
import requests
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime

ADAPTADOR = "Wi-Fi"

# ================= FUNCIONES BASE =================

def cambiar_dns(nombre):
    dns_opciones = {
        "Cloudflare": ("1.1.1.1", "1.0.0.1"),
        "Google": ("8.8.8.8", "8.8.4.4"),
        "OpenDNS": ("208.67.222.222", "208.67.220.220")
    }
    dns1, dns2 = dns_opciones[nombre]
    os.system(f'netsh interface ip set dns name="{ADAPTADOR}" static {dns1}')
    os.system(f'netsh interface ip add dns name="{ADAPTADOR}" {dns2} index=2')
    registrar_log(f"DNS cambiado a {nombre}")
    messagebox.showinfo("DNS", f"DNS cambiado a {nombre}")

def limpiar_cache_dns():
    os.system("ipconfig /flushdns")
    registrar_log("Caché DNS limpiado")
    messagebox.showinfo("DNS", "Caché DNS limpiado.")

def reiniciar_adaptador():
    os.system(f'netsh interface set interface "{ADAPTADOR}" admin=disable')
    time.sleep(3)
    os.system(f'netsh interface set interface "{ADAPTADOR}" admin=enable')
    registrar_log("Adaptador de red reiniciado")
    messagebox.showinfo("Red", "Adaptador reiniciado.")

def registrar_log(mensaje):
    with open("log_optimizador.txt", "a", encoding="utf-8") as log:
        log.write(f"{datetime.now()} - {mensaje}\n")

def estado_red():
    try:
        ip_local = os.popen("ipconfig").read().split("IPv4")[1].split(":")[1].split("\n")[0].strip()
    except:
        ip_local = "No encontrada"
    try:
        ip_publica = requests.get("https://api.ipify.org").text
    except:
        ip_publica = "No disponible"
    resumen.set(f"📶 IP Local: {ip_local}\n🌍 IP Pública: {ip_publica}")
    registrar_log("Estado de red consultado")

def verificar_conexion():
    try:
        requests.get("https://www.google.com", timeout=2)
        registrar_log("Conexión verificada: OK")
        messagebox.showinfo("Conexión", "✅ Tienes acceso a Internet.")
    except:
        registrar_log("Conexión verificada: SIN ACCESO")
        messagebox.showwarning("Conexión", "❌ No tienes acceso a Internet.")

# ============== TEST + RECOMENDACIONES ==============

def test_velocidad():
    status.set("Realizando test...")
    try:
        s = speedtest.Speedtest()
        s.get_best_server()
        bajada = s.download() / 1_000_000
        subida = s.upload() / 1_000_000
        ping = s.results.ping

        resultado = f"↓ {bajada:.2f} Mbps  ↑ {subida:.2f} Mbps  🕒 Ping: {ping:.0f} ms"
        registrar_log("Test velocidad: " + resultado)
        status.set(resultado)
        analizar_y_recomendar(bajada, subida, ping)
    except Exception as e:
        status.set("⚠️ Error en test")
        messagebox.showerror("Error", f"No se pudo ejecutar el test: {e}")

def analizar_y_recomendar(bajada, subida, ping):
    recomendaciones = []
    if bajada < 10:
        recomendaciones.append("🔁 Velocidad baja. Cambia DNS o usa cable.")
    if subida < 3:
        recomendaciones.append("📤 Subida limitada. Evita apps como Drive.")
    if ping > 100:
        recomendaciones.append("🐢 Ping alto. Cierra apps en 2do plano.")
    if not recomendaciones:
        recomendaciones.append("✅ Conexión óptima.")

    recos.set("\n".join(recomendaciones))
    registrar_log("Recomendaciones generadas.")

# ============== MODOS ESPECIALES ==============

def modo_juego():
    recos.set("🎮 MODO JUEGO\n\n- Cierra apps de fondo\n- Usa cable\n- DNS: Cloudflare")
    cambiar_dns("Cloudflare")
    limpiar_cache_dns()

def modo_ahorro():
    recos.set("💡 MODO AHORRO\n\n- Baja calidad en video\n- Apagar apps pesadas\n- DNS: Google")
    cambiar_dns("Google")

def hilo(funcion, *args):
    threading.Thread(target=lambda: funcion(*args)).start()

# ================= INTERFAZ ADAPTABLE =================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

app = ctk.CTk()
app.title("⚙️ OPTIMIZADOR DE INTERNET PRO 3.1")
app.state("zoomed")  # Pantalla completa al iniciar

# === Scrollable frame para adaptarse ===
scroll_frame = ctk.CTkScrollableFrame(app)
scroll_frame.pack(padx=20, pady=20, fill="both", expand=True)

# === TITULO ===
ctk.CTkLabel(scroll_frame, text="🛠️ Optimización Inteligente de Red", font=("Segoe UI", 28, "bold")).pack(pady=20)

# === BOTONES FUNCIONALES ===

def boton_responsive(texto, accion):
    ctk.CTkButton(scroll_frame, text=texto, command=accion, height=45, font=("Segoe UI", 16)).pack(pady=8, padx=60, fill="x")

# Principales
boton_responsive("🔍 Test de Velocidad + Recomendación", lambda: hilo(test_velocidad))
boton_responsive("🌐 Ver Estado de Red", lambda: hilo(estado_red))
boton_responsive("✅ Verificar Conexión a Internet", lambda: hilo(verificar_conexion))

ctk.CTkLabel(scroll_frame, text="──────────────", font=("Segoe UI", 16)).pack(pady=10)

# Modos
boton_responsive("🎮 Activar Modo Juego", lambda: hilo(modo_juego))
boton_responsive("💡 Activar Modo Ahorro", lambda: hilo(modo_ahorro))

ctk.CTkLabel(scroll_frame, text="──────────────", font=("Segoe UI", 16)).pack(pady=10)

# Extras
boton_responsive("🧹 Limpiar Caché DNS", lambda: hilo(limpiar_cache_dns))
boton_responsive("🔄 Reiniciar Adaptador", lambda: hilo(reiniciar_adaptador))
boton_responsive("🌎 Cambiar DNS a OpenDNS", lambda: hilo(cambiar_dns, "OpenDNS"))

# === DATOS EN TIEMPO REAL ===

status = ctk.StringVar(value="🕒 Esperando test de velocidad...")
ctk.CTkLabel(scroll_frame, textvariable=status, font=("Segoe UI", 14), text_color="#cccccc", wraplength=1200, justify="center").pack(pady=10)

resumen = ctk.StringVar(value="📡 Estado de IP pendiente...")
ctk.CTkLabel(scroll_frame, textvariable=resumen, font=("Segoe UI", 13), text_color="#cccccc", wraplength=1200, justify="center").pack(pady=10)

recos = ctk.StringVar(value="📌 Aquí aparecerán recomendaciones según tu red.")
ctk.CTkLabel(scroll_frame, text="📌 Recomendaciones Inteligentes:", font=("Segoe UI", 16, "bold")).pack(pady=(20, 5))
ctk.CTkLabel(scroll_frame, textvariable=recos, font=("Segoe UI", 13), text_color="#bbbbbb", wraplength=1200, justify="left").pack(pady=10)

app.mainloop()
