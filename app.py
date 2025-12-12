from flask import Flask, request, jsonify
import xmlrpc.client
import pandas as pd
from datetime import datetime, timedelta
import re
import os
from collections import defaultdict

# Configurar Flask
app = Flask(__name__)

# Tabla de BPM por tubo
BPM_TABLE = {
    14: 23,
    15: 23,
    16: 23,
    18: 19,
    19: 19,
    20: 19,
    21: 17,
    23: 13,
    500: 4,
    1: 0,
    0: 0,
    100: 3,
    101: 0.0083,
    102: 0.033,
    103: 0.016,
    104: 0.05,
    105: 0,
    2: 0
}

# Función para extraer contenido entre corchetes
def extraer_contenido_corchetes(texto):
    match = re.search(r'\[(.*?)\]', texto)
    return match.group(1) if match else None

@app.route('/produccion', methods=['GET'])
def obtener_produccion():
    try:
        # Datos de conexión (pueden ser configurables con variables de entorno)
        url = os.getenv('ODOO_URL', 'https://erp.snackselvalle.com')
        db = os.getenv('ODOO_DB', 'snackselvalle_fc0268f0')
        username = os.getenv('ODOO_USERNAME', 'josemiruiz@snackselvalle.com')
        password = os.getenv('ODOO_PASSWORD', '@Contraseña123')

        # Autenticación
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        uid = common.authenticate(db, username, password, {})

        if not uid:
            return jsonify({"error": "Error de autenticación"}), 401

        # Acceso a los modelos de Odoo
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

        # Filtro para órdenes de producción
        domain = [('state', 'in', ['draft', 'confirmed', 'progress', 'to_close'])]
        production_ids = models.execute_kw(db, uid, password, 'mrp.production', 'search', [domain])

        results = []
        fechas_finalizacion_maquina = {}
        excluir_materias = ['GFIJSNACKS', 'ACEGAO', 'SAL', 'GAS', 'PAT', 'GFIJPATAFRIT', 'gasfijmenos50gr', 'GASTEMBOLSAR', 'ACEG']

        # Diccionario para agrupar materiales
        materiales_agrupados = defaultdict(lambda: {'Cantidad a Consumir': 0, 'Máquinas': set(), 'Productos': set(), 'Horas': None, 'Fecha de Finalización': None})

        # Obtener información de productos (tubos) para todas las órdenes
        product_ids_set = set()
        productions_data = []
        
        for production_id in production_ids:
            production = models.execute_kw(db, uid, password, 'mrp.production', 'read', [production_id], {
                'fields': ['name', 'origin', 'sequence', 'product_id', 'product_qty']
            })[0]
            
            machine_name = production['origin'] if production['origin'] else 'Sin origen'
            
            if 'maquina' not in machine_name.lower():
                continue
                
            productions_data.append(production)
            if production['product_id']:
                product_ids_set.add(production['product_id'][0])

        # Obtener información de tubos para todos los productos
        product_tube_map = {}
        if product_ids_set:
            products_info = models.execute_kw(
                db, uid, password,
                'product.product', 'search_read',
                [[['id', 'in', list(product_ids_set)]]],
                {'fields': ['id', 'name', 'tube']}
            )
            product_tube_map = {p['id']: p.get('tube', 0) for p in products_info}

        # Agrupar órdenes por máquina para calcular las 8 horas
        MAX_HOURS = 8
        orders_by_machine = defaultdict(list)
        
        for production in productions_data:
            machine_name = production['origin'] if production['origin'] else 'Sin origen'
            orders_by_machine[machine_name].append(production)

        # Ordenar órdenes por sequence dentro de cada máquina
        for machine_name in orders_by_machine:
            orders_by_machine[machine_name].sort(key=lambda x: x['sequence'])

        # Procesar órdenes de producción con lógica de 8 horas
        for machine_name, machine_orders in orders_by_machine.items():
            accumulated_hours = 0
            
            for production in machine_orders:
                production_id = production['id']
                production_sequence = production['sequence']
                product_name = production['product_id'][1] if production['product_id'] else 'Sin producto'
                product_qty = production['product_qty'] if production['product_qty'] else 0
                product_id = production['product_id'][0] if production['product_id'] else None

                # Obtener el tubo del producto
                tube = product_tube_map.get(product_id, 0) if product_id else 0
                bpm = BPM_TABLE.get(tube, 0)

                # Calcular tiempo usando BPM si está disponible
                if bpm > 0:
                    # Tiempo para la orden completa
                    time_hours_complete = product_qty / (bpm * 60)
                    
                    # Verificar si cabe en las 8 horas
                    if accumulated_hours + time_hours_complete <= MAX_HOURS:
                        # Cabe completa
                        bolsas_a_producir = product_qty
                        horas = time_hours_complete
                        accumulated_hours += time_hours_complete
                    elif accumulated_hours < MAX_HOURS:
                        # Cabe parcialmente
                        remaining_hours = MAX_HOURS - accumulated_hours
                        bolsas_a_producir = remaining_hours * bpm * 60
                        horas = remaining_hours
                        accumulated_hours = MAX_HOURS
                    else:
                        # Ya se completaron las 8 horas, saltar esta orden
                        continue
                else:
                    # Fallback al cálculo original si no hay BPM
                    if "maquina 3" in machine_name.lower():
                        horas = product_qty / 1800
                    else:
                        horas = product_qty / 1020
                    bolsas_a_producir = product_qty

                # Calcular fecha de finalización
                if production_sequence == 0:
                    fecha_finalizacion = datetime.now() + timedelta(hours=horas)
                else:
                    fecha_finalizacion = fechas_finalizacion_maquina.get(machine_name, datetime.now()) + timedelta(hours=horas)

                fechas_finalizacion_maquina[machine_name] = fecha_finalizacion

                # Obtener materiales de la orden
                stock_move_ids = models.execute_kw(db, uid, password, 'stock.move', 'search', [
                    [('raw_material_production_id', '=', production_id), ('product_uom_qty', '>', 0)]
                ])

                stock_moves = models.execute_kw(db, uid, password, 'stock.move', 'read', [stock_move_ids], {
                    'fields': ['product_id', 'product_uom_qty']
                })

                for move in stock_moves:
                    material_name = move['product_id'][1]
                    contenido_corchetes = extraer_contenido_corchetes(material_name)

                    if contenido_corchetes and contenido_corchetes in excluir_materias:
                        continue

                    # Ajustar cantidad de material proporcionalmente
                    material_qty_original = move['product_uom_qty']
                    if bpm > 0:
                        # Ajustar proporcionalmente según las bolsas a producir
                        material_qty = material_qty_original * (bolsas_a_producir / product_qty)
                    else:
                        material_qty = material_qty_original

                    # Agrupar materiales
                    materiales_agrupados[material_name]['Cantidad a Consumir'] += material_qty
                    materiales_agrupados[material_name]['Máquinas'].add(machine_name)
                    materiales_agrupados[material_name]['Productos'].add(product_name)

                    # Actualizar la fecha de finalización más cercana
                    nueva_fecha = fecha_finalizacion.strftime('%Y-%m-%d %H:%M:%S')
                    if (materiales_agrupados[material_name]['Fecha de Finalización'] is None or
                            nueva_fecha < materiales_agrupados[material_name]['Fecha de Finalización']):
                        materiales_agrupados[material_name]['Fecha de Finalización'] = nueva_fecha

                    materiales_agrupados[material_name]['Horas'] = horas

                # Si ya se completaron las 8 horas para esta máquina, pasar a la siguiente
                if accumulated_hours >= MAX_HOURS:
                    break

        # Convertir agrupaciones a resultados finales
        for material_name, data in materiales_agrupados.items():
            results.append({
                'Material (Producto)': material_name,
                'Cantidad a Consumir': data['Cantidad a Consumir'],
                'Máquinas': ', '.join(data['Máquinas']),
                'Productos': ', '.join(data['Productos']),
                'Horas': data['Horas'],
                'Fecha de Finalización': data['Fecha de Finalización']
            })

        # Devolver resultados como JSON
        return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ejecutar el servidor en Railway
if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)