from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import numpy as np
from flask_cors import CORS
import datetime
import re

app = Flask(__name__)
CORS(app)  # Permite acesso do frontend

def extract_spec(text):
    """
    Extrai uma especificação no formato "número + unidade" (GB ou TB).
    Exemplo: "16GB", "500GB", "1TB", etc.
    """
    pattern = re.compile(r'(\d+)\s*(GB|TB)', re.IGNORECASE)
    match = pattern.search(text)
    if match:
        value = match.group(1)
        unit = match.group(2).upper()
        return f"{value}{unit}"
    return None

def get_price_estimate(query, max_ads=200):
    base_url = "https://www.olx.pt/ads/q-"
    page = 1
    prices = []

    # Extrai a especificação da query, se houver
    spec_query = extract_spec(query)
    if spec_query:
        print(f"Filtrando anúncios para a especificação: {spec_query}")

    while len(prices) < max_ads:
        url = f"{base_url}{query}/?page={page}"
        print(f"Acessando a URL: {url}")

        try:
            response = requests.get(url, timeout=10)
        except requests.exceptions.RequestException as e:
            print(f"Erro ao acessar a URL: {e}")
            break

        if response.status_code != 200:
            print(f"Erro ao acessar o OLX: {response.status_code}")
            break

        soup = BeautifulSoup(response.text, 'html.parser')
        ads = soup.find_all('li', {'data-testid': 'ad-list-item'})
        if not ads:
            print("Nenhum anúncio encontrado nesta página.")
            break

        for ad in ads:
            # Tenta extrair a especificação do título
            title_tag = ad.find('h6')
            title_text = title_tag.get_text(strip=True) if title_tag else ""
            spec_ad = extract_spec(title_text)
            # Fallback: tenta extrair de todo o texto do anúncio
            if not spec_ad:
                ad_text = ad.get_text(" ")
                spec_ad = extract_spec(ad_text)

            # Se a query especifica uma configuração, só considera o anúncio se bater exatamente
            if spec_query:
                if not spec_ad or spec_ad != spec_query:
                    continue

            price_tag = ad.find('p', {'data-testid': 'ad-price'})
            if not price_tag:
                continue
            price_text = price_tag.get_text(strip=True).replace('€', '').replace(',', '.').strip()
            try:
                price = float(price_text)
                prices.append(price)
            except ValueError:
                continue

            if len(prices) >= max_ads:
                break

        print(f"Total de anúncios coletados até agora: {len(prices)}")
        page += 1

    if not prices:
        print("❌ Nenhum anúncio válido encontrado.")
        return None

    # Remove outliers utilizando 2 desvios padrão e usa a mediana
    mean_price = np.mean(prices)
    std_dev = np.std(prices)
    filtered_prices = [p for p in prices if (mean_price - 2 * std_dev) <= p <= (mean_price + 2 * std_dev)]
    final_prices = filtered_prices if filtered_prices else prices
    median_price = np.median(final_prices)
    print(f"Preço mediano baseado em {len(final_prices)} anúncios: {median_price:.2f} €")
    return round(median_price, 2), len(final_prices)

@app.route("/price", methods=["GET"])
def get_price():
    query = request.args.get("query")
    if not query:
        return jsonify({"error": "Parâmetro 'query' é obrigatório."}), 400

    anoCompra = request.args.get("anoCompra")
    if not anoCompra:
        return jsonify({"error": "Parâmetro 'anoCompra' é obrigatório."}), 400

    estado = request.args.get("estado", "bom")

    # Obtém a estimativa de preço usando o scraper
    result = get_price_estimate(query)
    if not result:
        return jsonify({"error": "Nenhum anúncio encontrado."}), 404
    price_estimate, ads_count = result

    try:
        anoCompra_int = int(anoCompra)
    except ValueError:
        return jsonify({"error": "Ano de compra inválido."}), 400

    current_year = datetime.datetime.now().year
    age = current_year - anoCompra_int
    depreciation_rate = 0.05  # Depreciação de 5% por ano
    depreciation_factor = max(1 - (age * depreciation_rate), 0.5)

    # Aplica a depreciação e o ajuste do estado ao preço estimado
    base_final_price = round(price_estimate * depreciation_factor, 2)
    if estado == "novo":
        estado_factor = 1.1
    elif estado == "aceitável":
        estado_factor = 0.9
    else:
        estado_factor = 1.0
    final_price = round(base_final_price * estado_factor, 2)

    # Se a query contém "16GB", realiza uma consulta separada para "8GB"
    spec_query = extract_spec(query)
    if spec_query == "16GB":
        query_8gb = query.replace("16GB", "8GB")
        result_8gb = get_price_estimate(query_8gb)
        if result_8gb is not None:
            price_estimate_8gb, count_8gb = result_8gb
            base_final_price_8gb = round(price_estimate_8gb * depreciation_factor, 2)
            final_price_8gb = round(base_final_price_8gb * estado_factor, 2)
            print(f"Preço final para 8GB: {final_price_8gb} | Para 16GB (antes de ajuste): {final_price}")
            if final_price <= final_price_8gb:
                final_price = round(final_price_8gb * 1.1, 2)
                print("Ajustado preço 16GB para 10% maior que 8GB.")

    return jsonify({
        "query": query,
        "final_price": final_price,
        "ads_count": ads_count,
        "age": age,
        "depreciation_factor": depreciation_factor,
        "estado_factor": estado_factor
    })

if __name__ == "__main__":
    app.run(debug=True)
