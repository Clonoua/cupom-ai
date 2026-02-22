from fastapi import FastAPI, File, UploadFile, HTTPException, status
from fastapi.responses import JSONResponse
import ollama
import os
import json
import logging
from pathlib import Path
from typing import Dict

# Configura logging (útil para debug no servidor)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Processador de Cupons Fiscais - IA Vision",
    description="Extrai nome do estabelecimento, CNPJ, itens e valor total de cupons brasileiros",
    version="1.3.0"
)

# Configurações
MODEL = "qwen32b-custom"           # Seu modelo novo criado a partir do GGUF Q5_K_M
TEMP_DIR = Path("/tmp")
TEMP_IMAGE_PATH = TEMP_DIR / "temp_cupom.jpg"

# Prompt otimizado - só os campos que você quer
PROMPT = """
Você é especialista em extrair dados de cupons fiscais brasileiros (NFC-e).
Analise a imagem e extraia SOMENTE as informações abaixo como JSON válido.
Extraia EXATAMENTE o que está escrito, sem adivinhar nem corrigir valores ou nomes.
Preste atenção em letras parecidas (B vs O/D, 0 vs O, 1 vs l/I) e números decimais.
Ignore ruído, transparência do papel, texto do verso ou qualquer coisa fora da lista.

Estrutura exata do JSON (não adicione nem remova campos):

{
  "nome_estabelecimento": "string (razão social ou nome fantasia)",
  "cnpj": "string (ex: 08.616.988/0005-53)",
  "itens": [
    {
      "descricao": "string (nome do produto)",
      "quantidade": "string (ex: 0,280Kg ou 1UN ou 1 caixa)",
      "preco_unitario": number,
      "preco_total": number
    }
  ],
  "valor_total": number,
  "parcelamento": number
}

Responda APENAS com o JSON válido, sem texto antes ou depois.
Se algum campo não existir, use null ou lista vazia.
"""

@app.post("/processar_cupom", summary="Processa imagem de cupom e retorna dados essenciais")
async def processar_cupom(file: UploadFile = File(...)):
    """
    Recebe imagem de cupom fiscal e retorna JSON com:
    - Nome do estabelecimento + CNPJ
    - Itens (descrição, quantidade, preço unitário, preço total)
    - Valor total
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser uma imagem")

    try:
        # Salva temporariamente
        with open(TEMP_IMAGE_PATH, "wb") as buffer:
            buffer.write(await file.read())

        logger.info(f"Imagem salva temporariamente: {TEMP_IMAGE_PATH} (tamanho: {TEMP_IMAGE_PATH.stat().st_size} bytes)")

        # Chama Ollama com o modelo novo
        response = ollama.chat(
            model=MODEL,
            messages=[{
                'role': 'user',
                'content': PROMPT,
                'images': [str(TEMP_IMAGE_PATH)]
            }]
        )

        conteudo = response['message']['content'].strip()
        logger.info(f"Resposta bruta do Ollama (primeiros 200 chars): {conteudo[:200]}...")

        # Remove blocos markdown comuns que o modelo adiciona
        if conteudo.startswith("```json
            conteudo = conteudo[7:-3].strip()
        elif conteudo.startswith("```") and conteudo.endswith("```"):
            conteudo = conteudo[3:-3].strip()

        # Tenta parsear como JSON
        try:
            resultado: Dict = json.loads(conteudo)
        except json.JSONDecodeError as e:
            logger.warning(f"Erro ao parsear JSON: {e}")
            resultado = {
                "raw_response": conteudo,
                "error": "O modelo não retornou JSON válido. Veja raw_response acima."
            }

        # Validação simples de soma dos itens vs total (ajuda a detectar erros do modelo)
        if isinstance(resultado, dict) and "itens" in resultado and "valor_total" in resultado:
            try:
                soma_calculada = sum(float(item.get("preco_total", 0)) for item in resultado["itens"])
                total_declarado = float(resultado["valor_total"])
                if abs(soma_calculada - total_declarado) > 0.01:
                    resultado["aviso_soma"] = (
                        f"Soma calculada dos itens ({soma_calculada:.2f}) "
                        f"difere do total declarado ({total_declarado:.2f}). "
                        "Possível erro no modelo - verifique os valores."
                    )
            except (TypeError, ValueError):
                resultado["aviso_soma"] = "Não foi possível validar a soma dos itens (valores inválidos)."

        return JSONResponse(content=resultado)

    except Exception as e:
        logger.error(f"Erro ao processar requisição: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno ao processar a imagem: {str(e)}")

    finally:
        # Sempre remove o arquivo temporário
        if TEMP_IMAGE_PATH.exists():
            try:
                TEMP_IMAGE_PATH.unlink()
                logger.info("Arquivo temporário removido com sucesso")
            except Exception as e:
                logger.warning(f"Falha ao remover arquivo temporário: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
