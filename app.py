from flask import Flask, request, jsonify
import xmlrpc.client
import pandas as pd
from datetime import datetime, timedelta
import re
import os

# Configurar Flask
app = Flask(__name__)

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

        # Procesar órdenes de producción
        for production_id in production_ids:
            production = models.execute_kw(db, uid, password, 'mrp.production', 'read', [production_id], {
                'fields': ['name', 'origin', 'sequence', 'product_id', 'product_qty']
            })[0]

            machine_name = production['origin'] if production['origin'] else 'Sin origen'

            if 'maquina' not in machine_name.lower():
                continue

            production_sequence = production['sequence']
            product_name = production['product_id'][1] if production['product_id'] else 'Sin producto'
            product_qty = production['product_qty'] if production['product_qty'] else 0

            if "maquina 3" in machine_name.lower():
                horas = product_qty / 1800
            else:
                horas = product_qty / 1020

            if production_sequence == 0:
                fecha_finalizacion = datetime.now() + timedelta(hours=horas)
            else:
                fecha_finalizacion = fechas_finalizacion_maquina.get(machine_name, datetime.now()) + timedelta(hours=horas)

            fechas_finalizacion_maquina[machine_name] = fecha_finalizacion

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

                material_qty = move['product_uom_qty']

                results.append({
                    'Máquina (Origen)': machine_name,
                    'Producto a Fabricar': product_name,
                    'Cantidad a Fabricar': product_qty,
                    'Material (Producto)': material_name,
                    'Cantidad a Consumir': material_qty,
                    'Horas': horas,
                    'Fecha de Finalización': fecha_finalizacion.strftime('%Y-%m-%d %H:%M:%S')
                })

        # Devolver resultados como JSON
        return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ejecutar el servidor en Railway
if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
