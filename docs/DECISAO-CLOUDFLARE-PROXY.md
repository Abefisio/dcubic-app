# Decisão: app.dcubic pelo proxy da Cloudflare

**Data:** 29/10/2026
**Decisão:** o domínio `app.dcubic.reloadcursos.com` passa a ser servido pelo proxy da Cloudflare (nuvem laranja), com SSL **Full (strict)**.

## Motivo

O envio de STL grande era limitado pela rede entre o Brasil e a VPS em Frankfurt (RTT ~220 ms; uma conexão sobe 1,0–1,7 MB/s). Com o proxy, o navegador envia para a borda da Cloudflare em São Paulo, e a Cloudflare leva os dados até a VPS.

## Medição (29/10/2026, Mac do Dr. Abe → VPS, 4 partes em paralelo, SHA-256 conferido)

| Teste | Direto | Pela Cloudflare | Ganho |
|---|---|---|---|
| 300 MiB (3 rodadas) | 2:02 (2,70 MB/s) | 0:31 (10,79 MB/s) | 3,9× |
| 3 GB | 24:03 (2,23 MB/s, 2 rodadas) | 4:24 (12,45 MB/s, 1 rodada) | 5,4× |
| Quedas de conexão em 3 GB | 17 | nenhuma | — |

O certificado Let's Encrypt (HTTP-01) foi emitido normalmente com o proxy ativo.

Relatório completo: `~/Desktop/RELATORIOS-CLAUDE/cloudflare-teste-medicao.txt`.

## Alterações no painel Cloudflare (zona reloadcursos.com)

1. Configuration Rule "app.dcubic Full strict": `http.host eq "app.dcubic.reloadcursos.com"` → SSL Full (strict).
2. Registro A `app.dcubic` → `152.239.113.183` passou de DNS only (nuvem cinza) para Proxied (nuvem laranja).
3. Registros de teste `teste-envio.dcubic` e `teste-envio-direto.dcubic` apagados.

"Always Use HTTPS" permanece **desligado**. É o que permite a renovação do certificado por HTTP-01 na porta 80. Nada foi alterado na VPS.

## Cuidados

- Não ligar "Always Use HTTPS" nem criar redirect http→https na Cloudflare para `*.dcubic`: isso quebra a renovação do certificado de origem (vence em 27/01/2027 e o Traefik renova sozinho).
- Partes de envio devem ficar abaixo de 100 MB (limite por pedido do plano gratuito). Hoje elas têm até 16 MiB (ver abaixo).
- Rocket Loader e Bot Fight Mode devem permanecer desligados.

## Envio real em produção e redução da parte para 16 MiB

Em 29/10/2026, às 17:42, `feat/envio-rapido` (e1fec9f) foi publicada na VPS. O envio real de 300 MiB pela Cloudflare, com login e 4 partes em paralelo, levou **61,8 s (5,13 MB/s)**. Foram 13 partes, todas com status 200, e o SHA-256 conferiu no servidor. A parte mais lenta, de 32 MiB, levou **54 s**, muito perto do corte de 60 s do Traefik (`readTimeout` padrão do entrypoint, que não alteramos).

Decisão: o teto da parte no navegador (`assets/envio_grande/index.html`, `PARTE_MAX`) caiu de 32 MiB para **16 MiB**, mantidos os 4 PUTs em paralelo. Nessa mesma velocidade, uma parte de 16 MiB leva ~27 s, com folga para o corte. O servidor continua aceitando até 32 MiB, para que abas abertas com a versão anterior sigam funcionando. Uma parte que falha (queda de rede, tempo esgotado no cliente, 5xx do proxy como 502/504/524, 408/429) volta para a fila e é reenviada automaticamente, depois de consultar o servidor sobre quais blocos já chegaram.

Relatórios: `~/Desktop/RELATORIOS-CLAUDE/envio-rapido-publicacao.txt` e `~/Desktop/RELATORIOS-CLAUDE/envio-16mib.txt`.

O usuário temporário do teste foi removido. Antes, o arquivo de usuários foi copiado para `/docker/dcubic/segredos/users.yaml.bak-20261029-204328` (backup mantido na VPS); depois do teste, `/docker/dcubic/segredos/users.yaml` foi restaurado e conferido por sha256 contra esse backup.

## Como reverter

No painel Cloudflare → reloadcursos.com → DNS → Records, mudar `app.dcubic` de volta para **nuvem cinza (DNS only)**. A mudança vale em segundos e se completa em até ~5 min. Nada precisa ser feito na VPS. A Configuration Rule pode ficar, porque não tem efeito com a nuvem cinza.
