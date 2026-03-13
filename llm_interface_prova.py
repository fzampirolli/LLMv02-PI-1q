#!/usr/bin/env python3
"""
Interface unificada para API DeepSeek (substitui Groq)
Arquivo: llm_interface_prova.py

Cliente assíncrono para chamadas à API DeepSeek com:
  - Retry com backoff exponencial
  - Fallback para múltiplos modelos (se configurado)
  - Rate limiting adaptativo
  - Extração de metadados (modelo usado, tempo, tokens)
"""


import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from contextlib import asynccontextmanager

import aiohttp
import yaml

logger = logging.getLogger(__name__)

# =============================================================================
# ESTRUTURAS DE DADOS
# =============================================================================

@dataclass
class LLMResponse:
    """Resposta padronizada de qualquer LLM."""
    success: bool
    content: Optional[str] = None
    model_used: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


# =============================================================================
# CLIENTE DEEPSEEK CORRIGIDO
# =============================================================================

class DeepSeekClient:
    """
    Cliente assíncrono para API DeepSeek.
    """
    
    def __init__(self, config: Dict):
        """
        Args:
            config: dicionário carregado do config.yaml
        """
        self.config = config
        deepseek_cfg = config.get('deepseek', {})
        
        self.api_key = deepseek_cfg.get('api_key')
        if not self.api_key:
            raise ValueError("DeepSeek API key não encontrada no config.yaml")
        
        self.api_url = deepseek_cfg.get(
            'api_url', 
            "https://api.deepseek.com/v1/chat/completions"
        )
        
        # Modelo principal
        self.model = deepseek_cfg.get('model', "deepseek-chat")
        
        # Lista de modelos para fallback
        self.models = deepseek_cfg.get('models', [self.model])
        if not self.models:
            self.models = [self.model]
        
        self.temperature = deepseek_cfg.get('temperature', 0.7)
        
        # === CORREÇÃO: Limitar max_tokens ao range permitido (1-8192) ===
        self.max_response_chars = deepseek_cfg.get('max_response_chars', 100000)
        self.min_response_chars = deepseek_cfg.get('min_response_chars', 5)
        
        # DeepSeek aceita no máximo 8192 tokens
        # 1 token ≈ 4 caracteres em média
        self.max_tokens = min(8192, self.max_response_chars // 4)
        # Garantir mínimo de 1 token
        self.max_tokens = max(1, self.max_tokens)
        
        logger.info(f"DeepSeek max_tokens configurado para: {self.max_tokens}")
        
        # Rate limiting
        self.requests_per_minute = 60
        self._request_timestamps = []
        self._semaphore = asyncio.Semaphore(5)
        
        # Sessão HTTP
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()
    
    async def _wait_for_rate_limit(self):
        """Controle de taxa simples."""
        now = time.time()
        self._request_timestamps = [t for t in self._request_timestamps if now - t < 60]
        
        if len(self._request_timestamps) >= self.requests_per_minute:
            oldest = self._request_timestamps[0]
            sleep_time = 60 - (now - oldest)
            if sleep_time > 0:
                logger.debug(f"Rate limit: aguardando {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
        
        self._request_timestamps.append(time.time())
    
    async def _make_request(
        self, 
        session: aiohttp.ClientSession,
        model: str,
        messages: List[Dict[str, str]],
        timeout: int = 120
    ) -> Dict:
        """Executa uma requisição única com timeout."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,  # CORRIGIDO: valor dentro do range
            "stream": False
        }
        
        logger.debug(f"Enviando requisição para {model} com max_tokens={self.max_tokens}")
        
        async with session.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {error_text}")
            
            return await resp.json()
    
    async def chat_completion(
        self,
        system_prompt: str,
        user_content: str,
        timeout_per_try: int = 120
    ) -> LLMResponse:
        """
        Envia prompt para DeepSeek com retry e fallback entre modelos.
        """
        start_time = time.time()
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        # Embaralha modelos para distribuir carga
        models_to_try = self.models.copy()
        random.shuffle(models_to_try)
        
        last_error = None
        
        async with self._semaphore:
            await self._wait_for_rate_limit()
            
            for attempt, model in enumerate(models_to_try):
                try:
                    logger.debug(f"Tentativa {attempt+1} com modelo: {model}")
                    
                    data = await self._make_request(
                        self._session, model, messages, timeout_per_try
                    )
                    
                    # Extrai conteúdo
                    content = data['choices'][0]['message']['content']
                    
                    # Verifica tamanho mínimo
                    if len(content.strip()) < self.min_response_chars:
                        raise ValueError(f"Resposta muito curta ({len(content)} chars)")
                    
                    # Trunca se necessário (usando caracteres, não tokens)
                    if len(content) > self.max_response_chars:
                        content = content[:self.max_response_chars] + "\n[TRUNCADO...]"
                    
                    # Extrai uso de tokens
                    usage = data.get('usage', {})
                    
                    elapsed = time.time() - start_time
                    
                    logger.info(f"Sucesso com {model} em {elapsed:.1f}s")
                    
                    return LLMResponse(
                        success=True,
                        content=content,
                        model_used=model,
                        duration_seconds=elapsed,
                        prompt_tokens=usage.get('prompt_tokens'),
                        completion_tokens=usage.get('completion_tokens'),
                        total_tokens=usage.get('total_tokens')
                    )
                    
                except asyncio.TimeoutError:
                    last_error = f"Timeout após {timeout_per_try}s"
                    logger.warning(f"Timeout com {model}: {last_error}")
                    
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Falha com {model}: {last_error}")
                    
                    # Se for erro de autenticação ou saldo, não adianta tentar outros
                    if "401" in last_error or "unauthorized" in last_error.lower() or "402" in last_error:
                        break
                
                # Pequena pausa entre tentativas
                if attempt < len(models_to_try) - 1:
                    await asyncio.sleep(1)
            
            # Todas as tentativas falharam
            elapsed = time.time() - start_time
            return LLMResponse(
                success=False,
                error=last_error or "Todas as tentativas falharam",
                duration_seconds=elapsed
            )


# =============================================================================
# INTERFACE DE ALTO NÍVEL
# =============================================================================

class LLMClientProva:
    """Wrapper para manter compatibilidade com código existente."""
    
    def __init__(self, config: Dict):
        self.config = config
        self._client: Optional[DeepSeekClient] = None
    
    async def __aenter__(self):
        self._client = DeepSeekClient(self.config)
        await self._client.__aenter__()
        return self
    
    async def __aexit__(self, *args):
        if self._client:
            await self._client.__aexit__(*args)
    
    async def chat_completion(
        self,
        system_prompt: str,
        user_content: str
    ) -> LLMResponse:
        """Mantém mesma assinatura da versão Groq."""
        if not self._client:
            raise RuntimeError("Cliente não inicializado (use async with)")
        
        return await self._client.chat_completion(system_prompt, user_content)


# =============================================================================
# PROCESSAMENTO EM LOTE ASSÍNCRONO
# =============================================================================

async def process_students_async(
    client: LLMClientProva,
    tasks: List[Tuple[str, str, Dict]],
    max_concurrent: int = 3
) -> List[Tuple[Dict, LLMResponse]]:
    """
    Processa múltiplos alunos em paralelo com controle de concorrência.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = []
    
    async def _process_one(system_prompt: str, user_content: str, metadata: Dict):
        async with semaphore:
            response = await client.chat_completion(system_prompt, user_content)
            return metadata, response
    
    # Cria todas as tasks
    coros = [_process_one(prompt, content, meta) for prompt, content, meta in tasks]
    
    # Executa em paralelo e coleta resultados na ordem
    for future in asyncio.as_completed(coros):
        try:
            metadata, response = await future
            results.append((metadata, response))
            
            # Log resumido
            status = "✓" if response.success else "✗"
            model = response.model_used or "N/A"
            duration = response.duration_seconds
            logger.info(f"{status} {metadata['student']} | {model} | {duration:.1f}s")
            
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
    
    return results