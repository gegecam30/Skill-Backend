import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # IMPORTANTE: Añade esta importación
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Optional

# Cargamos las variables de entorno
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("🚨 ERROR: No se encontró el archivo .env o faltan las credenciales.")

# Cliente ANON: Solo para autenticación (login, register)
supabase_anon: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cliente ADMIN (service_role): Para todas las operaciones de base de datos (ignora RLS)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY or SUPABASE_KEY)

app = FastAPI(
    title="SkillSwap Campus API",
    description="Backend para el ecosistema de intercambio de habilidades"
)

# ---------------------------------------------------------
# CONFIGURACIÓN CORS (Permite que el frontend hable con el backend)
# ---------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "https://skillswap.gexel.fun"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"status": "online", "message": "¡Servidor de SkillSwap Campus activo!"}

from pydantic import BaseModel

# ---------------------------------------------------------
# MODELOS DE DATOS (PYDANTIC) - Nuestro escudo de seguridad
# ---------------------------------------------------------
class ServiceCreate(BaseModel):
    provider_id: str
    title: str
    description: str
    price: int

# ---------------------------------------------------------
# ENDPOINTS DE LA API
# ---------------------------------------------------------
@app.post("/services/")
def create_service(service: ServiceCreate):
    """
    Crea un nuevo servicio en el Marketplace.
    Valida la información antes de tocar la base de datos.
    """
    # 1. Validación de seguridad en el backend
    if service.price <= 0:
        return {"error": "Operación rechazada: El precio debe ser mayor a 0 CH."}

    # 2. Inserción segura en Supabase
    try:
        response = supabase.table("services").insert({
            "provider_id": service.provider_id,
            "title": service.title,
            "description": service.description,
            "price": service.price
        }).execute()
        
        return {"success": True, "message": "Servicio publicado exitosamente", "data": response.data}
    
    except Exception as e:
        return {"error": f"Error interno del servidor: {str(e)}"}
    
    
# ---------------------------------------------------------
# ENDPOINT DEL MARKETPLACE (Con Misiones de Tutorial)
# ---------------------------------------------------------
@app.get("/services/")
def get_all_services():
    """
    Obtiene los servicios de Supabase y añade misiones de tutorial
    para que el Marketplace nunca esté vacío.
    """
    try:
        # 1. MISIONES DE SISTEMA (Inyectadas en memoria)
        system_missions = [
            {
                "id": "mission-001",
                "provider_id": "system",
                "provider_name": "SkillSwap System",
                "title": "[ MISIÓN ] Aprende a usar el Escrow",
                "description": "Contrata este servicio gratuito para entender cómo se congelan los créditos de forma segura. Al finalizar, recibirás un bono de +20 CH.",
                "price": 0,
                "tags": ["Tutorial", "Recompensa"],
                "bg": "#ff2a6d",  # Color especial neón
                "initials": "SYS"
            },
            {
                "id": "mission-002",
                "provider_id": "system",
                "provider_name": "Comunidad UPC",
                "title": "[ SOCIAL ] Únete a la red",
                "description": "Conecta con otros estudiantes en nuestra red. Contrata esto por 0 CH para completar tu inducción.",
                "price": 0,
                "tags": ["Comunidad", "Onboarding"],
                "bg": "#A78BFA",
                "initials": "UPC"
            }
        ]

        # 2. Consultar servicios reales de los usuarios (solo los activos)
        response = supabase.table("services").select("*").eq("status", "active").execute()
        real_services = response.data if response.data else []

        # Formatear los servicios reales para que el frontend los lea igual
        formatted_real_services = []
        for s in real_services:
            formatted_real_services.append({
                "id": s.get("id"),
                "provider_id": s.get("provider_id"),
                "provider_name": "Estudiante", # Próximamente lo cruzaremos con la tabla perfiles
                "title": s.get("title"),
                "description": s.get("description"),
                "price": s.get("price"),
                "tags": ["Servicio"],
                "bg": "#00e5ff",
                "initials": "STU"
            })

        # 3. Unir misiones + servicios reales
        all_services = system_missions + formatted_real_services

        return {"success": True, "services": all_services}

    except Exception as e:
        return {"error": f"Error al cargar el marketplace: {str(e)}"}

@app.patch("/services/{service_id}/accept")
def accept_service(service_id: str):
    """Marca un servicio como aceptado para que no aparezca más en el marketplace"""
    try:
        # Verificar que el servicio exista y esté activo
        res = supabase.table("services").select("status").eq("id", service_id).execute()
        if not res.data:
            return {"error": "Servicio no encontrado"}
        if res.data[0].get("status") == "accepted":
            return {"error": "Este servicio ya ha sido aceptado por otro usuario"}
            
        # Marcarlo como aceptado
        supabase.table("services").update({"status": "accepted"}).eq("id", service_id).execute()
        return {"success": True}
    except Exception as e:
        return {"error": f"Error al aceptar servicio: {str(e)}"}
# ---------------------------------------------------------
# NUEVO MODELO DE DATOS
# ---------------------------------------------------------
class TransactionCreate(BaseModel):
    sender_id: str
    receiver_id: str
    service_id: str
    amount: int

# ---------------------------------------------------------
# ENDPOINT DE ESCROW (Seguridad Crítica)
# ---------------------------------------------------------
@app.post("/transactions/escrow")
def create_escrow_transaction(txn: TransactionCreate):
    """
    Inicia un intercambio. Congela los CH del comprador en un 'escrow'.
    """
    if txn.amount <= 0:
        return {"error": "El monto debe ser mayor a 0 CH."}
    
    if txn.sender_id == txn.receiver_id:
         return {"error": "No puedes contratarte a ti mismo."}

    try:
        # 1. Verificar saldo del comprador
        sender_profile = supabase.table("profiles").select("balance").eq("id", txn.sender_id).execute()
        
        if not sender_profile.data:
            return {"error": "Usuario comprador no encontrado."}
            
        current_balance = sender_profile.data[0]['balance']
        
        if current_balance < txn.amount:
             return {"error": f"Fondos insuficientes. Tienes {current_balance} CH, necesitas {txn.amount} CH."}

        # 2. Operación Atómica (Restar saldo y crear transacción)
        new_balance = current_balance - txn.amount
        supabase.table("profiles").update({"balance": new_balance}).eq("id", txn.sender_id).execute()
        
        # ── NUEVO: Si el receiver es 'system' (tutorial), no insertamos en transacciones ──
        if txn.receiver_id == "system":
            return {
                "success": True,
                "message": f"Escrow de tutorial completado: {txn.amount} CH simulados.",
                "data": [{"id": "escrow_tutorial_123", "status": "escrow"}]
            }

        # Creamos la transacción en estado 'escrow' para usuarios reales
        response = supabase.table("transactions").insert({
            "sender_id": txn.sender_id,
            "receiver_id": txn.receiver_id,
            "service_id": txn.service_id,
            "amount": txn.amount,
            "status": "escrow"
        }).execute()

        return {
            "success": True, 
            "message": f"Escrow activado: {txn.amount} CH congelados.", 
            "data": response.data
        }

    except Exception as e:
        return {"error": f"Error procesando la transacción: {str(e)}"}

# ---------------------------------------------------------
# ENDPOINT DE BÚSQUEDA DE EXPERTOS REALES
# ---------------------------------------------------------
@app.get("/profiles/category/{category}")
def get_experts_by_category(category: str):
    """
    Busca usuarios en la base de datos que ofrezcan una categoría específica en sus skills.
    Nota: Supabase Postgres usa el operador 'cs' (contains) para buscar dentro de arrays JSON.
    """
    try:
        # Busca perfiles donde el arreglo 'skills' contenga la categoría (ignorando mayúsculas exactas a nivel UI, pero aquí buscaremos textualmente o traeremos todos para filtrar en caso de diferencias de formato).
        # Para mayor robustez, traemos todos los perfiles y filtramos en Python para ignorar mayúsculas/minúsculas de manera fácil, ya que es un prototipo.
        response = supabase.table("profiles").select("*").execute()
        if not response.data:
            return {"success": True, "experts": []}
            
        real_experts = []
        search_cat = category.lower().strip()
        
        for p in response.data:
            user_skills = [s.lower().strip() for s in p.get("skills", [])] if p.get("skills") else []
            # Hacemos match parcial o exacto
            if any(search_cat in s for s in user_skills):
                real_experts.append({
                    "id": p["id"],
                    "name": p.get("display_name") or p.get("university_code") or "Experto",
                    "major": "Miembro SkillSwap",
                    "bg": "#60A5FA",
                    "icon": "🧑‍🎓",
                    "portfolio": ["Trabajo 1", "Trabajo 2"],
                    "rating": 5.0,
                    "completed": p.get("completedTasks", 0),
                    "avatar_url": p.get("avatar_url")
                })
                
        return {"success": True, "experts": real_experts}
    except Exception as e:
        return {"error": f"Error buscando expertos: {str(e)}"}
    

# ---------------------------------------------------------
# MODELOS DE DATOS (Actualizados para aceptar Email)
# ---------------------------------------------------------
class RegisterRequest(BaseModel):
    name: str
    email: str  # Cambiamos 'code' por 'email'
    password: str
    skills: str

class LoginRequest(BaseModel):
    email: str  # Cambiamos 'code' por 'email'
    password: str

# ---------------------------------------------------------
# ENDPOINTS DE AUTENTICACIÓN (Con lógica de Bonos)
# ---------------------------------------------------------
@app.post("/auth/register")
def register_user(req: RegisterRequest):
    """Registra usuario, aplica filtros y da bonos por ser estudiante"""
    email = req.email.lower().strip()
    
    # 1. Lógica del Bono Universitario
    is_edu = email.endswith(".edu") or email.endswith(".edu.pe")
    bonus = 40 if is_edu else 0
    initial_balance = 100 + bonus

    # ── NUEVO: Extraemos el código de estudiante del correo ──
    # Ejemplo: "u202517715@upc.edu.pe" -> "u202517715"
    uni_code = email.split('@')[0].upper() if is_edu else None

    try:
        # 2. Creación en Supabase Auth
        res = supabase_anon.auth.sign_up({
            "email": email,
            "password": req.password,
            "options": {
                "data": {
                    "display_name": req.name
                }
            }
        })
        
        # 3. Forzamos el perfil enviando el university_code
        if res.user:
            # Si es externo, generamos un código único usando parte de su UUID (max 20 chars)
            final_uni_code = uni_code if is_edu else f"EXT-{res.user.id[:8].upper()}"
            
            skills_list = [s.strip() for s in req.skills.split(',')]
            supabase.table("profiles").upsert({
                "id": res.user.id,
                "display_name": req.name,
                "university_code": final_uni_code, # <--- ENVIAMOS EL CÓDIGO ÚNICO AQUÍ
                "skills": skills_list,
                "balance": initial_balance,
                "is_verified_student": is_edu
            }).execute()
            
        return {
            "success": True, 
            "message": "Revisa tu bandeja de entrada para verificar tu cuenta.",
            "bonus_applied": is_edu
        }
    except Exception as e:
        return {"error": f"Error al registrar: {str(e)}"}

@app.post("/auth/login")
def login_user(req: LoginRequest):
    """Inicia sesión usando Email en lugar de código"""
    email = req.email.lower().strip()
    try:
        res = supabase_anon.auth.sign_in_with_password({
            "email": email,
            "password": req.password
        })
        return {"success": True, "user_id": res.user.id, "message": "Acceso concedido."}
    except Exception as e:
        # Si no ha verificado el correo, Supabase lanzará el error aquí
        return {"error": f"Credenciales incorrectas o correo no verificado."}
    
# ---------------------------------------------------------
# ENDPOINT DE PERFIL (Dashboard)
# ---------------------------------------------------------
@app.get("/profile/{user_id}")
def get_user_profile(user_id: str):
    """
    Obtiene los datos reales del usuario desde la tabla profiles de Supabase.
    """
    try:
        # Consultamos la tabla profiles filtrando por el ID del usuario
        response = supabase.table("profiles").select("*").eq("id", user_id).execute()
        
        if not response.data:
            return {"error": "Perfil no encontrado en la base de datos."}
        
        return {"success": True, "profile": response.data[0]}
    
    except Exception as e:
        return {"error": f"Error al conectar con la base de datos: {str(e)}"}
    
# ---------------------------------------------------------
# ENDPOINT PARA RECOMPENSAS DE MISIONES
# ---------------------------------------------------------
class ProfileUpdateRequest(BaseModel):
    display_name: str
    skills: list[str]

@app.patch("/profile/{user_id}")
def update_profile(user_id: str, req: ProfileUpdateRequest):
    """Actualiza el nombre y habilidades del perfil"""
    try:
        response = supabase.table("profiles").update({
            "display_name": req.display_name,
            "skills": req.skills
        }).eq("id", user_id).execute()
        
        if not response.data:
            return {"error": "No se pudo actualizar el perfil."}
            
        return {"success": True, "profile": response.data[0]}
    except Exception as e:
        return {"error": f"Error interno: {str(e)}"}

# ---------------------------------------------------------
# ENDPOINT PARA RECOMPENSAS DE MISIONES
# ---------------------------------------------------------
class RewardRequest(BaseModel):
    user_id: str
    amount: int

@app.post("/profile/reward")
def reward_user(req: RewardRequest):
    """Suma créditos directamente a la base de datos tras completar misiones"""
    try:
        # 1. Consultar saldo actual
        profile = supabase.table("profiles").select("balance").eq("id", req.user_id).execute()
        if not profile.data:
            return {"error": "Perfil no encontrado."}
        
        current_balance = profile.data[0].get("balance", 100)
        new_balance = current_balance + req.amount
        
        # 2. Actualizar en Supabase de manera permanente
        supabase.table("profiles").update({"balance": new_balance}).eq("id", req.user_id).execute()
        
        return {"success": True, "new_balance": new_balance}
    except Exception as e:
        return {"error": f"Error al procesar recompensa: {str(e)}"}
    
    # ---------------------------------------------------------
# ENDPOINTS DEL SOCIAL FEED
# ---------------------------------------------------------
class PostCreate(BaseModel):
    author_id: str
    content: str
    category: str
    image_url: Optional[str] = None

@app.post("/posts/")
def create_post(post: PostCreate):
    """Guarda un nuevo post en la base de datos"""
    try:
        post_data = {
            "author_id": post.author_id,
            "content": post.content,
            "category": post.category
        }
        if post.image_url:
            post_data["image_url"] = post.image_url
        
        response = supabase.table("posts").insert(post_data).execute()
        return {"success": True, "post": response.data[0]}
    except Exception as e:
        return {"error": f"Error al publicar: {str(e)}"}

@app.get("/posts/")
def get_posts():
    """Obtiene todos los posts ordenados por fecha y con los datos del autor"""
    try:
        # Hacemos un 'join' con profiles para traer el nombre y código del autor
        response = supabase.table("posts").select(
            "id, content, category, image_url, created_at, profiles(display_name, university_code, avatar_url)"
        ).order("created_at", desc=True).execute()
        
        return {"success": True, "posts": response.data}
    except Exception as e:
        return {"error": f"Error al cargar el feed: {str(e)}"}
    
# ---------------------------------------------------------
# ENDPOINT DE ESTADÍSTICAS EN TIEMPO REAL
# ---------------------------------------------------------
@app.get("/platform/stats/{user_id}")
def get_platform_stats(user_id: str):
    """Obtiene datos reales de la plataforma y las conexiones del usuario"""
    try:
        # 1. Total de usuarios (Tamaño de la red)
        users_res = supabase.table("profiles").select("id", count="exact").execute()
        total_users = users_res.count if users_res.count else 1
        
        # 2. Intercambios activos (Transacciones en estado 'escrow')
        tx_res = supabase.table("transactions").select("id", count="exact").eq("status", "escrow").execute()
        active_exchanges = tx_res.count if tx_res.count else 0
        
        # 3. Conexiones (Cuántos intercambios ha hecho ESTE usuario)
        user_tx = supabase.table("transactions").select("id", count="exact").or_(f"sender_id.eq.{user_id},receiver_id.eq.{user_id}").execute()
        my_connections = user_tx.count if user_tx.count else 0
        
        return {
            "success": True, 
            "online": total_users, # Sin WebSockets, mostramos el total de la red
            "exchanges": active_exchanges,
            "connections": my_connections
        }
    except Exception as e:
        return {"error": str(e)}
    
# ---------------------------------------------------------
# MODELO Y ENDPOINT PARA ACTUALIZACIÓN DE AVATAR
# ---------------------------------------------------------
class AvatarUpdateRequest(BaseModel):
    user_id: str
    avatar_url: str

@app.post("/profile/update-avatar")
def update_profile_avatar(req: AvatarUpdateRequest):
    """Actualiza la ruta o URL pública del avatar en la base de datos"""
    try:
        response = supabase.table("profiles").update({
            "avatar_url": req.avatar_url
        }).eq("id", req.user_id).execute()
        
        if not response.data:
            return {"error": "No se pudo actualizar el avatar. Perfil no encontrado."}
            
        return {"success": True, "avatar_url": req.avatar_url}
    except Exception as e:
        return {"error": f"Error interno en el servidor: {str(e)}"}

# ---------------------------------------------------------
# ENDPOINTS DE MENSAJERÍA (Chat Simple)
# ---------------------------------------------------------
class MessageCreate(BaseModel):
    sender_id: str
    receiver_id: str
    content: str

@app.post("/messages/")
def send_message(msg: MessageCreate):
    """Envía un mensaje de un usuario a otro"""
    try:
        response = supabase.table("messages").insert({
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "content": msg.content
        }).execute()
        return {"success": True, "message": response.data[0]}
    except Exception as e:
        return {"error": f"Error al enviar mensaje: {str(e)}"}

@app.get("/messages/{user1_id}/{user2_id}")
def get_messages(user1_id: str, user2_id: str):
    """Obtiene el historial de chat entre dos usuarios"""
    try:
        response = supabase.table("messages").select("*").or_(
            f"and(sender_id.eq.{user1_id},receiver_id.eq.{user2_id}),and(sender_id.eq.{user2_id},receiver_id.eq.{user1_id})"
        ).order("created_at", desc=False).execute()
        return {"success": True, "messages": response.data}
    except Exception as e:
        return {"error": f"Error al cargar mensajes: {str(e)}"}

# ---------------------------------------------------------
# ENDPOINTS DE ADMINISTRADOR / MODERACIÓN
# ---------------------------------------------------------
def check_admin(admin_id: str):
    res = supabase.table("profiles").select("role").eq("id", admin_id).execute()
    if not res.data or res.data[0].get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acceso denegado: Se requieren permisos de administrador.")

@app.delete("/admin/posts/{post_id}")
def admin_delete_post(post_id: str, admin_id: str):
    try:
        check_admin(admin_id)
        supabase.table("posts").delete().eq("id", post_id).execute()
        return {"success": True}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        return {"error": str(e)}

@app.delete("/admin/services/{service_id}")
def admin_delete_service(service_id: str, admin_id: str):
    try:
        check_admin(admin_id)
        supabase.table("services").delete().eq("id", service_id).execute()
        return {"success": True}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        return {"error": str(e)}

@app.post("/admin/ban/{user_id}")
def admin_ban_user(user_id: str, admin_id: str, ban: bool = True):
    try:
        check_admin(admin_id)
        supabase.table("profiles").update({"is_banned": ban}).eq("id", user_id).execute()
        return {"success": True, "message": "Usuario baneado" if ban else "Usuario desbaneado"}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        return {"error": str(e)}