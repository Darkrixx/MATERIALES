import xmlrpc.client
import pandas as pd
from datetime import datetime, timedelta
import re  # Para manejar la extracción de texto dentro de los corchetes

# Datos de conexión
url = 'https://erp.snackselvalle.com'
db = 'snackselvalle_fc0268f0'
username = 'josemiruiz@snackselvalle.com'
password = '@Contraseña123'

# Autenticación
common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
uid = common.authenticate(db, username, password, {})

if uid:
    print('Autenticación exitosa, UID:', uid)
else:
    print('Error de autenticación')
    exit()

# Acceso a los modelos de Odoo
models = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))

# Filtro para órdenes de producción con los estados: "draft", "confirmed", "progress", "to_close"
domain = [('state', 'in', ['draft', 'confirmed', 'progress', 'to_close'])]

# Obtener las órdenes de producción filtradas
production_ids = models.execute_kw(db, uid, password, 'mrp.production', 'search', [domain])

# Lista para almacenar los resultados
results = []

# Diccionario para rastrear la última fecha de finalización por máquina
fechas_finalizacion_maquina = {}

# Materias primas que debemos excluir (comparar solo con el contenido dentro de los corchetes)
excluir_materias = ['GFIJSNACKS', 'ACEGAO', 'SAL', 'GAS', 'PAT', 'GFIJPATAFRIT', 'gasfijmenos50gr','GASTEMBOLSAR','ACEG']

# Función para extraer el contenido entre corchetes
def extraer_contenido_corchetes(texto):
    # Buscar el contenido dentro de corchetes con regex
    match = re.search(r'\[(.*?)\]', texto)
    if match:
        return match.group(1)
    return None  # Si no hay corchetes, devolver None

# Recorrer cada orden de producción
for production_id in production_ids:
    # Obtener los detalles de la orden de producción, incluyendo el campo `origin`, `sequence`, `product_id` (producto a fabricar) y `product_qty` (cantidad a fabricar)
    production = models.execute_kw(db, uid, password, 'mrp.production', 'read', [production_id], {'fields': ['name', 'origin', 'sequence', 'product_id', 'product_qty']})
    
    # Obtener el nombre de la máquina (origen)
    machine_name = production[0]['origin'] if production[0]['origin'] else 'Sin origen'
    
    # Filtrar solo las órdenes que contienen la palabra "MAQUINA" en el origen
    if "maquina" not in machine_name.lower():
        continue
    
    # Obtener la secuencia de la orden de producción, el producto a fabricar, y la cantidad a fabricar
    production_sequence = production[0]['sequence']
    product_name = production[0]['product_id'][1] if production[0]['product_id'] else 'Sin producto'
    product_qty = production[0]['product_qty'] if production[0]['product_qty'] else 0
    
    # Calcular las horas según la máquina (división 1800 para máquina 3 y 1020 para las otras máquinas)
    if "maquina 3" in machine_name.lower():
        horas = product_qty / 1800
    else:
        horas = product_qty / 1020
    
    # Calcular la fecha de finalización
    if production_sequence == 0:
        # Si es la primera secuencia (0), sumar las horas al tiempo actual
        fecha_finalizacion = datetime.now() + timedelta(hours=horas)
    else:
        # Si es una secuencia posterior, sumar las horas a la fecha de finalización anterior para la misma máquina
        if machine_name in fechas_finalizacion_maquina:
            fecha_finalizacion = fechas_finalizacion_maquina[machine_name] + timedelta(hours=horas)
        else:
            # Si no hay una fecha anterior registrada (caso improbable), usar el tiempo actual
            fecha_finalizacion = datetime.now() + timedelta(hours=horas)
    
    # Actualizar la fecha de finalización para esta máquina
    fechas_finalizacion_maquina[machine_name] = fecha_finalizacion
    
    # Buscar los movimientos de stock (stock.move) relacionados con las materias primas consumidas en la producción
    stock_move_ids = models.execute_kw(db, uid, password, 'stock.move', 'search', [
        [('raw_material_production_id', '=', production_id), ('product_uom_qty', '>', 0)]  # Eliminamos el filtro de 'state'
    ])
    
    # Obtener detalles de los movimientos de stock, incluyendo el `product_id` y la cantidad `product_uom_qty` (a consumir)
    stock_moves = models.execute_kw(db, uid, password, 'stock.move', 'read', [stock_move_ids], {'fields': ['product_id', 'product_uom_qty']})
    
    # Añadir una fila por cada material (componente) asociado a la máquina y la secuencia de producción
    first_row = True
    for move in stock_moves:
        material_name = move['product_id'][1]
        
        # Extraer el contenido de los corchetes en el nombre del material
        contenido_corchetes = extraer_contenido_corchetes(material_name)
        
        # Excluir solo si el contenido de los corchetes coincide exactamente con alguna de las materias a excluir
        if contenido_corchetes and contenido_corchetes in excluir_materias:
            print(f"Excluyendo material: {material_name}")  # Depuración: Mostrar si se excluye algún material
            continue
        
        material_qty = move['product_uom_qty']
        
        # Solo mostrar la secuencia, la máquina, el producto, cantidad a fabricar y el cálculo de horas en la primera fila
        if first_row:
            results.append({
                'Máquina (Origen)': machine_name,
                'Producto a Fabricar': product_name,
                'Cantidad a Fabricar': product_qty,
                'Material (Producto)': material_name,
                'Cantidad a Consumir': material_qty,
                'Horas': horas,
                'Fecha de Finalización': fecha_finalizacion.strftime('%Y-%m-%d %H:%M:%S')
            })
            first_row = False
        else:
            results.append({
                'Máquina (Origen)': '',
                'Producto a Fabricar': '',
                'Cantidad a Fabricar': '',
                'Material (Producto)': material_name,
                'Cantidad a Consumir': material_qty,
                'Horas': '',
                'Fecha de Finalización': ''
            })

# Convertir los resultados en un DataFrame de pandas
df = pd.DataFrame(results)

# Guardar el DataFrame en un archivo Excel en la ubicación indicada (sin ordenar)
output_file = 'C:/Users/Josemi Ruiz Vilches/Desktop/produccion_con_filtro_exacto.xlsx'
df.to_excel(output_file, index=False)

output_file
