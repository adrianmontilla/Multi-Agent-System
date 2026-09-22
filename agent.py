import sys
import subprocess
import shutil
import urllib.request
import urllib.error
import json
import os
from dotenv import load_dotenv
from pathlib import Path
from google.adk.agents import LlmAgent, ParallelAgent, LoopAgent, SequentialAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools import ToolContext
from . import rag   
#from rag import consultar_documentacion 

load_dotenv()

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_RETRIES = 5
current_retries = 0
best_mas_state = {}
best_error_count = float('inf')


def resolve_jason_command():
    """
    Busca el ejecutable de Jason en este orden:
    1. Variable de entorno JASON_BIN
    2. Comando 'jason' disponible en el PATH
    3. Ruta típica de macOS (/Applications/jason)
    4. Ruta típica de Windows (C:\\Jason\\bin\\jason.bat)
    """
    env_path_relative = os.getenv("JASON_BIN")

    if env_path_relative:
        env_path_absolute = str(Path(env_path_relative).absolute())
        return env_path_absolute

    path_command = shutil.which("jason")
    if path_command:
        return path_command

    default_macos_path = "/Applications/jason"
    if Path(default_macos_path).exists():
        return default_macos_path
    
    default_windows_paths = [
        r"C:\Jason\bin\jason.bat",
        r"C:\Program Files\Jason\bin\jason.bat",
        r"C:\Program Files (x86)\Jason\bin\jason.bat",
    ]
    for windows_path in default_windows_paths:
        if Path(windows_path).exists():
            return windows_path

    return None

def search_github_examples(path: str = "") -> str:
    """
    Permite acceder a los ejemplos oficiales de código de Jason (BDI) en GitHub.
    Útil para consultar cómo se implementan ciertas características en Jason.
    
    Args:
        path: La ruta relativa del archivo o directorio de ejemplo a consultar dentro de la carpeta 'examples' de Jason.
              Déjalo vacío ("") para listar los directorios y archivos de la raíz de ejemplos.
              Puedes usar esta herramienta primero con "" para ver qué ejemplos hay, y luego llamarla 
              de nuevo con la ruta específica, ej. "blocks/blocks.mas2j" o "auction/ag1.asl".
    """
    base_api_url = "https://api.github.com/repos/jason-lang/jason/contents/examples"
    url = f"{base_api_url}/{path}".strip("/")
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Python-urllib'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if isinstance(data, list):
                items = [f"[{item['type']}] {item['path'].replace('examples/', '', 1)}" for item in data]
                return f"Contenido de '{path or 'raíz'}':\n" + "\n".join(items)
            
            elif isinstance(data, dict) and data.get("type") == "file":
                download_url = data.get("download_url")
                if download_url:
                    req_file = urllib.request.Request(download_url, headers={'User-Agent': 'Python-urllib'})
                    with urllib.request.urlopen(req_file) as f_res:
                        return f_res.read().decode('utf-8')
                return "Error: No se encontró la URL de descarga del archivo."
            else:
                return "Respuesta inesperada de la API de GitHub."
                
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"Error: No se encontró la ruta '{path}' en los ejemplos de Jason."
        if e.code == 403:
            return "Error: Límite de peticiones a la API de GitHub excedido. Inténtalo más tarde."
        return f"Error HTTP al acceder a GitHub: {e.code} - {e.reason}"
    except Exception as e:
        return f"Error al intentar acceder a los ejemplos: {e}"

def test_mas_code(mas2j_code: str, agents_dict: dict) -> str:
    """
    Guarda y ejecuta el código en un directorio temporal para probar el sistema Multi-Agente usando jason.
    NO guarda los archivos definitivamente, solo devuelve la salida para que verifiques si funciona.
    Tiene un límite de 5 intentos por sesión.
    
    Args:
        mas2j_code: El contenido completo del archivo de configuración .mas2j.
        agents_dict: Un diccionario donde la clave es el nombre del archivo (ej. "agent1.asl") 
                     y el valor es el contenido de ese archivo .asl.
    """
    global current_retries, best_mas_state, best_error_count
    
    if current_retries >= MAX_RETRIES:
         return f"ERROR: Has superado el límite de {MAX_RETRIES} intentos. Por favor, utiliza 'save_mas_code' para guardar el último código de inmediato y termina tu respuesta."
         
    current_retries += 1
    
    temp_dir = Path("temp_mas_project")
    
    try:
        # Limpiar si ya existe
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir()
        
        # Guardar .mas2j
        mas2j_file = temp_dir / "temp.mas2j"
        mas2j_file.write_text(mas2j_code, encoding="utf-8")
        
        # Guardar archivos .asl
        for filename, content in agents_dict.items():
            if not filename.endswith(".asl"):
                filename += ".asl"
            (temp_dir / filename).write_text(content, encoding="utf-8")
            
        jason_command = resolve_jason_command()
        print(jason_command)
        if not jason_command:
            return (
                "ERROR: No se ha encontrado Jason. Instálalo y define la variable "
                "de entorno JASON_BIN o añade el comando 'jason' al PATH."
            )

        result = subprocess.run(
            [jason_command, "mas", "start", "--mas2j=temp.mas2j", "--console"],
            cwd=str(temp_dir),
            capture_output=True,
            text=True,
            timeout=15
        )

        
        # Heurística simple para contar errores basándonos en STDERR y el código de retorno
        error_count = 0
        if result.returncode != 0:
            error_count += 10
        if result.stderr:
            error_count += len(result.stderr.split('\n'))
            
        if error_count < best_error_count:
            best_error_count = error_count
            best_mas_state = {
                "mas2j": mas2j_code,
                "agents": agents_dict
            }
            
        # Format output
        output = f"=== EJECUCIÓN DE PRUEBA (Intento {current_retries}/{MAX_RETRIES}) ===\nReturn code: {result.returncode}\n"
        if result.stdout:
            output += f"--- STDOUT ---\n{result.stdout}\n"
        if result.stderr:
            output += f"--- STDERR ---\n{result.stderr}\n"
            
        return output
        
    except subprocess.TimeoutExpired as e:
        # En muchos sistemas, jason arranca la GUI y se queda pillado. Guardamos el estado.
        if best_error_count == float('inf'):
            best_mas_state = {
                "mas2j": mas2j_code,
                "agents": agents_dict
            }
            
        output = f"=== EJECUCIÓN DE PRUEBA (Intento {current_retries}/{MAX_RETRIES}) ===\n"
        output += "AVISO: La ejecución alcanzó el tiempo límite (15s). Esto es normal si Jason arranca una interfaz y no finaliza solo.\n"
        if hasattr(e, 'stdout') and e.stdout:
            stdout_str = e.stdout.decode('utf-8') if isinstance(e.stdout, bytes) else e.stdout
            output += f"--- STDOUT (parcial) ---\n{stdout_str}\n"
        return output
        
    except FileNotFoundError:
        return "ERROR: El comando 'jason' no se encuentra en el sistema. Asegúrate de tener instalado Jason y agregado al PATH."
    except Exception as e:
        return f"ERROR inesperado al ejecutar: {e}"
    finally:
        # Limpiar
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def exit_loop(tool_context: ToolContext):
    """Llama a esta función en caso de que ningún cambio deba realizarse en el código."""
    print(f"  [Tool Call] exit_loop triggered by {tool_context.agent_name}")
    tool_context.actions.escalate = True
    return {}

def save_mas_code(mas_name: str, mas2j_code: str = "", agents_dict: dict = None) -> str:
    """
    Guarda el sistema MAS completo (el .mas2j y los .asl) en su propia subcarpeta dentro de 'output'.
    Si provees 'mas2j_code' y 'agents_dict', guardará esos. Si están vacíos, usará el 'mejor' código que lograste ejecutar en tus pruebas.
    
    Args:
        mas_name: Nombre del proyecto (se usará para la subcarpeta en 'output' y el archivo .mas2j).
    """
    global current_retries, best_mas_state, best_error_count
    
    if agents_dict is None:
        agents_dict = {}
        
    project_dir = OUTPUT_DIR / mas_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    code_mas2j = mas2j_code if mas2j_code else best_mas_state.get("mas2j", "")
    code_agents = agents_dict if agents_dict else best_mas_state.get("agents", {})
    
    if not code_mas2j or not isinstance(code_agents, dict) or not code_agents:
         return "ERROR: No hay código generado para guardar o no se ha probado previamente."
         
    try:
        # Guardar .mas2j
        mas_filename = f"{mas_name}.mas2j" if not mas_name.endswith(".mas2j") else mas_name
        (project_dir / mas_filename).write_text(str(code_mas2j), encoding="utf-8")
        
        # Guardar .asl
        for filename, content in code_agents.items():
            if not filename.endswith(".asl"):
                filename += ".asl"
            (project_dir / filename).write_text(str(content), encoding="utf-8")
        
        # Resetear estado para próximas llamadas del usuario
        current_retries = 0
        best_mas_state = {}
        best_error_count = float('inf')
        
        return f"ÉXITO: Proyecto BDI guardado correctamente en {project_dir}"
    except Exception as e:
        return f"ERROR inesperado al guardar: {e}"

# Configuramos el modelo, asumiendo la configuración habitual
model = LiteLlm(
    #model="openai/gpt-oss-120b", 
    model= "openai/Qwen3.6-35B-A3B-FP8",
    api_base="https://api.poligpt.upv.es/",
    api_key= None #Para que funcione, debes tener una API key para acceder al modelo de la UPV
)

structural_agent = LlmAgent(
    name="BDI_Structural",
    model=model,
    description="Agente experto en diseñar estructuras de sistemas multiagentes en un archivo de configuración .mas2j",
    instruction=(
        "Eres un agente experto programador en AgentSpeak y Jason, orientado a sistemas Multi-Agente BDI (Belief-Desire-Intention). "
        "Tu objetivo es crear una estructura sobre proyectos MAS completos que cumplan con las especificaciones del usuario.\n\n"
        "INSTRUCCIONES CRÍTICAS:\n"
        "1. Analiza lo que pide el usuario y diseña la estructura del sistema: un archivo de configuración .mas2j y uno o más agentes en archivos .asl.\n"
        "2. IMPORTANTE SINTAXIS .mas2j: El archivo de configuración DEBE seguir estrictamente esta estructura:\n"
        "   MAS nombre_proyecto {\n"
        "       infrastructure: Centralised\n"
        "       agents:\n"
        "           nombre_agente_1;\n"
        "           nombre_agente_2 #3; /* Si necesitas instanciar 3 copias */\n"
        "   }\n"
        "   REGLAS MAS2J: Usa 'MAS' en mayúsculas. NO pongas la extensión '.asl' en la lista de agentes. Acaba cada declaración de agente con punto y coma (;).\n"
        "   MUY IMPORTANTE: El nombre de los agentes debe ir en minusculas y si es posible en snake_case.\n"
    ),
    output_key = "structure"
)
researcher_agent_github = LlmAgent(
    name="BDI_Researcher_GitHub",
    model=model,
    description="Agente experto en buscar información en github orientado en sistemas Multi-Agente BDI (Belief-Desire-Intention). ",
    instruction=(
        "Tu objetivo es buscar información usando la tool search_github_examples(path) para obtener inspiración para la estructura guardada en session.state['structure']\n\n"
        "INSTRUCCIONES CRÍTICAS:\n"
        "1. PASO 1 (INVESTIGACIÓN OBLIGATORIA): ESTÁS OBLIGADO a llamar a la herramienta 'search_github_examples(path)'.\n"
        "CATASTROFE DE SINTAXIS (MUY IMPORTANTE): Al usar la herramienta, SIEMPRE debes usar estrictamente el nombre técnico exacto ('search_github_examples'). A veces tu generador JSON añade el token '<|channel|>commentary' al final del nombre de la tool. ESTO PROVOCA UN ERROR FATAL. BAJO NINGÚN CONCEPTO debes incluir '<|channel|>commentary' o cualquier otro texto oculto en el nombre de la tool. Limítate a generar el nombre en minúsculas y tal cual es."
    ),
    tools=[search_github_examples],
    output_key="github_examples"
)


researcher_agent_local = LlmAgent(
    name="BDI_Researcher_Local",
    model=model,
    description="Agente experto en buscar información en archivos locales orientado en sistemas Multi-Agente BDI (Belief-Desire-Intention). ",
    instruction=(
        "Tu objetivo es buscar información usando la tool rag.search_local_docs(path) para obtener la teoría necesaria para implementar la estructura del sistema multiagente MAS definida en session.state['structure']\n\n"
        "INSTRUCCIONES CRÍTICAS:\n"
        "1. (INVESTIGACIÓN OBLIGATORIA): ESTÁS OBLIGADO a llamar a la herramienta 'rag.search_local_docs(path)'.\n"
        "CATASTROFE DE SINTAXIS (MUY IMPORTANTE): Al usar la herramienta, SIEMPRE debes usar estrictamente el nombre técnico exacto ('search_local_docs'). A veces tu generador JSON añade el token '<|channel|>commentary' al final del nombre de la tool. ESTO PROVOCA UN ERROR FATAL. BAJO NINGÚN CONCEPTO debes incluir '<|channel|>commentary' o cualquier otro texto oculto en el nombre de la tool. Limítate a generar el nombre en minúsculas y tal cual es."
    ),
    tools = [rag.search_local_docs],
    output_key="local_theory"
)

coding_agent = LlmAgent(
    name="BDI_Coding_Agent",
    model=model,
    description="Agente experto en programar archivos .asl en lenguaje AgentSpeak orientado en sistemas Multi-Agente BDI. ",
    instruction=(
        "Tu objetivo es programar archivos .asl que implemente los agentes en lenguaje AgentSpeak para la estructura del sistema multiagente MAS definida en session.state['structure']\n\n"
        "═══════════════════════════════════════════════════════════════════════════════\n"
        "REGLAS DE SINTAXIS AGENTSPEAK (.asl) - CRÍTICAS Y NO NEGOCIABLES\n"
        "═══════════════════════════════════════════════════════════════════════════════\n\n"
        "1. TERMINACIÓN OBLIGATORIA: Todos los planes, creencias y objetivos DEBEN terminar con PUNTO FINAL (.) al final de la línea\n"
        "   CORRECTO:   contador(0).\n"
        "   CORRECTO:   +!start : true <- .print(\"Hola\"); !next.\n"
        "   INCORRECTO: contador(0);\n"
        "   INCORRECTO: +!start : true <- .print(\"Hola\"), !next;\n\n"

        "2. SEPARADORES EN CUERPOS DE PLANES: PUNTO Y COMA (;) SIEMPRE\n"
        "   CORRECTO:   .print(\"A\"); .print(\"B\"); !next.\n"
        "   CORRECTO:   -belief(X); +belief(Y); +!goal.\n"
        "   INCORRECTO: .print(\"A\"), .print(\"B\"), !next;\n"
        "   INCORRECTO: -belief(X), +belief(Y), +!goal;\n\n"

        "3. CREENCIAS - ELIMINAR Y AÑADIR (- y +)\n"
        "   CORRECTO:   -contador(Old); +contador(New).\n"
        "   INCORRECTO: ~contador(Old); +contador(New).\n"
        "   NOTA: El símbolo (~) NO EXISTE en AgentSpeak. Usa (-) para eliminar.\n\n"

        "4. ESTRUCTURA BÁSICA DE UN PLAN - FORMATO ESTRICTO\n"
        "   +!objetivo(Parametros) : contexto <- acciones.\n"
        "   Donde:\n"
        "   - (+!) indica que es la cabecera de un plan\n"
        "   - (: contexto) es OPCIONAL pero ayuda a elegir el plan correcto\n"
        "   - (<-) separa el contexto de las acciones (NUNCA usar ->)\n"
        "   - (acciones) están separadas por punto y coma (;)\n"
        "   - Termina con PUNTO FINAL (.)\n\n"
        "   CORRECTO:\n"
        "   +!calcular : contador(C) & C < 10 <-\n"
        "       Next = C + 1;\n"
        "       -contador(C);\n"
        "       +contador(Next).\n\n"
        "   INCORRECTO:\n"
        "   +!calcular : contador(C) & C < 10 <-\n"
        "       Next = C + 1,\n"
        "       -contador(C),\n"
        "       +contador(Next);\n\n"

        "5. CONTEXTO DE PLANES - USAR & (AND) LÓGICO\n"
        "   CORRECTO:   +!plan : creencia1(X) & creencia2(Y) & X > 0 <- ...\n"
        "   INCORRECTO: +!plan : creencia1(X), creencia2(Y), X > 0 <- ...\n"
        "   NOTA: Las comas en el contexto NO están permitidas. Usa & para AND.\n\n"

        "6. OPERACIONES ARITMÉTICAS - PRIMERO EN VARIABLE\n"
        "   CORRECTO:\n"
        "       Suma = A + B;\n"
        "       !procesar(Suma).\n"
        "   INCORRECTO:\n"
        "       !procesar(A + B).\n\n"

        "7. ACCIONES NATIVAS (.print, .wait, etc)\n"
        "   CORRECTO:   .print(\"Valor: \", X); .wait(1000).\n"
        "   CORRECTO:   .print(A, B, C).\n"
        "   NOTA: Usa comas dentro de .print() para concatenar\n\n"

        "8. VARIABLES vs ÁTOMOS\n"
        "   - Variables: Comienzan con MAYÚSCULA (X, Counter, Result)\n"
        "   - Átomos (creencias): En minúscula (contador, my_belief, x)\n"

        "9. PLANES DE CONTINGENCIA - OBLIGATORIO\n"
        "   Siempre añade un plan de fallback genérico:\n"
        "   CORRECTO:\n"
        "       +!objetivo(X) : contextoNormal(X) <- ... .\n"
        "       +!objetivo(X) <- .print(\"Fallo en objetivo con \", X).\n\n"

        "10. COMENTARIOS\n"
        "   CORRECTO:   // Esto es un comentario\n"
        "   PROHIBIDO usar % para empezar una linea de comentario. DEBES usar //"

        "11. LLAMADAS A SUBOBJETIVOS\n"
        "   CORRECTO: \n" 
        "   ! (Solo exclamación): Se usa en el cuerpo del plan para llamar o ejecutar un subobjetivo.\n"
        "   Ejemplo: \n"
        """+!start : true <-
                .print("0, ");
                !calculate. // Invocación del subobjetivo (sin '+')"""
                
        "12. COMUNICACIÓN ENTRE AGENTES:\n"
        "   PROHIBIDO: \n" 
        "   Inventar funciones como 'trigger()'\n"
        "   CORRECTO: \n"
        "   Debes usar siempre la acción estándar .send(AgenteDestino, Performativa, Contenido)\n"
        "   REGLA ESTRICTA: \n"
        "   La 'Performativa' debe ser un acto comunicativo FIPA válido. Utiliza únicamente:\n"
            """'tell' (para enviar creencias)
                'achieve' (para delegar metas)
                'askOne' / 'askAll' (para consultar creencias)"""


        "═══════════════════════════════════════════════════════════════════════════════\n"
        "FLUJO DE TRABAJO\n"
        "═══════════════════════════════════════════════════════════════════════════════\n"
        "1. Consulta session.state['local_theory'] y session.state['github_examples'] para inspirarte.\n"
        "2. Si session.state['code_review'] contiene observaciones, úsalas para mejorar.\n"
        "3. Genera código limpio, revisado mentalmente, siguiendo EXACTAMENTE todas las reglas de arriba.\n"
        "4. El agente de revisión comprobará la sintaxis automáticamente.\n\n"

        "EJEMPLO PERFECTO (Cópialo como plantilla):\n"
        "// Creencias iniciales y objetivo\n"
        "valor(0).\n"
        "limite(5).\n"
        "!start.\n\n"
        "// Plan de inicio\n"
        "+!start : true <-\n"
        "    .print(\"Sistema iniciado\");\n"
        "    !procesar.\n\n"
        "// Plan principal\n"
        "+!procesar : valor(V) & V < 5 <-\n"
        "    Siguiente = V + 1;\n"
        "    .print(\"Valor: \", Siguiente);\n"
        "    -valor(V);\n"
        "    +valor(Siguiente);\n"
        "    !procesar.\n\n"
        "// Plan de término\n"
        "+!procesar : valor(V) & V >= 5 <-\n"
        "    .print(\"Proceso finalizado\").\n\n"
        "// Contingencia (siempre incluir)\n"
        "+!procesar : true <-\n"
        "    .print(\"Error: No hay plan para procesar\").\n"
    ),
    output_key="code_asl"
)

review_agent = LlmAgent(
    name="BDI_Reviewer_Agent",
    model=model,
    description="Agente experto en revisar código en lenguaje AgentSpeak y la estructura del sistema multiagente BDI",
    instruction=(
        "Tu objetivo es revisar EXHAUSTIVAMENTE el código guardado en session.state['code_asl'] y la estructura del sistema multiagente BDI definida en session.state['structure']\n\n"

        "═══════════════════════════════════════════════════════════════════════════════\n"
        "INSTRUCCIONES DE REVISIÓN EXHAUSTIVA\n"
        "═══════════════════════════════════════════════════════════════════════════════\n\n"

        "PASO 1: REVISIÓN ESTÁTICA (SIN EJECUTAR)\n"
        "Verifica TODAS estas reglas en el código antes de probarlo:\n\n"

        "A) TERMINACIÓN CON PUNTO (.)\n"
        "   - TODAS las creencias DEBEN terminar con punto: contador(0).\n"
        "   - TODOS los planes DEBEN terminar con punto: +!start : true <- .print(\"x\").\n"
        "   - TODOS los objetivos iniciales DEBEN terminar con punto: !start.\n"
        "   Si encuentras líneas que terminan con (,) o (;) cuando debería ser (.), ES UN ERROR CRÍTICO.\n\n"

        "B) SEPARADORES EN PLANES\n"
        "   - Dentro de un plan, acciones se separan SIEMPRE con PUNTO Y COMA (;)\n"
        "   - NUNCA debes usar COMAS (,) para separar acciones\n"
        "   - Errores típicos:\n"
        "     .print(\"x\"), !next;     // COMA entre acciones = ERROR\n"
        "     -belief(X), +belief(Y); // COMA antes de la siguiente acción = ERROR\n"
        "   - Soluciones: \n"
        "     .print(\"x\"); !next.    // PUNTO Y COMA entre acciones = CORRECTO\n"
        "     -belief(X); +belief(Y). // PUNTO Y COMA entre acciones = CORRECTO\n\n"

        "C) OPERADOR DE ELIMINACIÓN DE CREENCIAS\n"
        "   - SOLO existe (-) para eliminar creencias.\n"
        "   - El símbolo (~) NO EXISTE en AgentSpeak.\n"
        "   - Errores típicos:\n"
        "     ~contador(X); +contador(Y). // (~) no existe\n"
        "   - Solucion:\n"
        "     -contador(X); +contador(Y). // (-) es correcto\n\n"

        "D) ESTRUCTURA DE PLANES\n"
        "   - Todo plan DEBE tener el formato: +!objetivo(Parametros) : contexto <- acciones.\n"
        "   - El contexto puede estar vacío (usar ':  true' o ':' directamente)\n"
        "   - NUNCA uses (->) en lugar de (<-)\n"
        "   - El contexto usa (&) para AND lógico, NUNCA comas (,)\n"
        "   - Errores típicos:\n"
        "     +!goal(X) : cond1(Y), cond2(Z) <- ... // COMA en contexto\n"
        "   - Solución: \n"
        "     +!goal(X) : cond1(Y) & cond2(Z) <- ... // & en contexto\n\n"

        "E) OPERACIONES ARITMÉTICAS\n"
        "   - Primero ASIGNA el resultado a una variable, luego ÚSALO\n"
        "   - Errores típicos:\n"
        "     !procesar(A + B).       // Operación directa en argumento\n"
        "   - Solución: \n"
        "     Suma = A + B; !procesar(Suma). // Asignar primero\n\n"

        "F) VARIABLES vs ÁTOMOS\n"
        "   - Variables: Primera letra MAYÚSCULA (X, Valor, Counter)\n"
        "   - Átomos: Primera letra minúscula (x, valor, counter)\n"
        "   - Inconsistencias hacen que el código no compile.\n\n"

        "G) ACCIONES NATIVAS (.print, .wait, etc)\n"
        "   - Siempre llevan un punto delante: .print(), .wait(), etc\n"
        "   - Dentro de .print() usa COMAS para separar argumentos, NO (+)\n"
        "   - Errores típicos:\n"
        "     .print(\"Valor: \" + X); // NUNCA concatenar strings\n"
        "   - Solución: \n"
        "     .print(\"Valor: \", X); // Usar comas para separar\n\n"

        "═══════════════════════════════════════════════════════════════════════════════\n"
        "PASO 2: EJECUCIÓN Y ANÁLISIS DE ERRORES\n"
        "═══════════════════════════════════════════════════════════════════════════════\n"
        "1. LLAMA SIEMPRE a 'test_mas_code' con:\n"
        "   - mas2j_code: la estructura MAS de session.state['structure']\n"
        "   - agents_dict: el código ASL de session.state['code_asl']\n"
        "2. Analiza la salida:\n"
        "   - Si return code = 0 y sin errores en STDERR: ÉXITO, usa exit_loop()\n"
        "   - Si hay errores: Lee STDERR y STDOUT para identificar qué falló\n\n"

        "PASO 3: REPORTE DE ERRORES\n"
        "Si test_mas_code falla, devuelve un JSON con esta estructura exacta:\n"
        "{\n"
        "  \"problems\": [\n"
        "    \"descripción específica del error 1\",\n"
        "    \"descripción específica del error 2\"\n"
        "  ],\n"
        "  \"suggestions\": [\n"
        "    \"cómo arreglar el error 1\",\n"
        "    \"cómo arreglar el error 2\"\n"
        "  ]\n"
        "}\n\n"
        "ERRORES COMUNES A BUSCAR:\n"
        "- 'No plan for event': Falta un plan o está mal escrito\n"
        "- 'Syntax error': Problema de puntuación (,;.)\n"
        "- 'Unknown internal action': Acción nativa mal escrita\n"
        "- 'Inconsistent belief/goal': Variable/átomo mal nombrado\n\n"

        "PASO 4: ÉXITO\n"
        "Si test_mas_code ejecuta sin errores, llama a exit_loop() para terminar el bucle.\n\n"

        "CATASTROFE DE SINTAXIS (MUY IMPORTANTE):\n"
        "Al usar herramientas, SIEMPRE usa exactamente estos nombres:\n"
        "- test_mas_code (NUNCA 'test_mas_code<|channel|>commentary')\n"
        "- exit_loop (NUNCA con textos ocultos)\n"
    ),
    tools = [test_mas_code, exit_loop],
    output_key="code_review"
)


submmit_agent = LlmAgent(
    name="BDI_Submmit_Agent",
    model=model,
    description="Agente que guarda el resultado de los anteriores agentes en un archivo .mas2j y .asl en carpetas dentro de 'output'",
    instruction=(
        "Tu objetivo es consolidar el código final y guardarlo en el sistema de archivos.\n\n"
        "INSTRUCCIONES CRÍTICAS:\n"
        "1.(Guardado Final): estás OBLIGADO a llamar a 'save_mas_code' con la estructura definida en session.state['structure'] y el código guardado en session.state['code_asl'] para persistir el proyecto, .\n"
        "2.(Notificar al usuario): Informa del éxito de la creación y da un breve resumen.\n"
        "3. REGLA DE NOMENCLATURA: El nombre del proyecto MAS (la palabra que va justo después de 'MAS') DEBE empezar SIEMPRE con letra minúscula(ej. 'fibonacci_system'). NUNCA uses letras mayúsculas al inicio.\n"
        "CATASTROFE DE SINTAXIS (MUY IMPORTANTE): Al usar la herramienta, SIEMPRE debes usar estrictamente el nombre técnico exacto ('save_mas_code'). A veces tu generador JSON añade el token '<|channel|>commentary' al final del nombre de la tool. ESTO PROVOCA UN ERROR FATAL. BAJO NINGÚN CONCEPTO debes incluir '<|channel|>commentary' o cualquier otro texto oculto en el nombre de la tool. Limítate a generar el nombre en minúsculas y tal cual es."
    ),
    tools = [save_mas_code]
)

researcher_agents = ParallelAgent(
    name="BDI_Parallel_Agent",
    sub_agents=[researcher_agent_github, researcher_agent_local]
)

code_review_agents = LoopAgent(
    name="BDI_Loop_Agent",
    sub_agents=[coding_agent, review_agent],
    max_iterations=5
)


root_agent = SequentialAgent(
    name="BDI_Root_Agent",
    sub_agents=[structural_agent, researcher_agents, code_review_agents, submmit_agent]
)
