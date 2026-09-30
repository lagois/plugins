# BeerGoPi 0.11Beta — Controle dinâmico

Base: 0.10Beta. Mantém Receitas, Monitor, Histórico, gráfico e os cinco comandos.

Implementa offset T1, histerese, intervalo de leitura, intervalo de telemetria, referência/potência de fervura, recirculação cíclica, tempos de bomba e bomba no aquecimento. Configurações em dados/configuracoes.json; eventos de alterações no histórico.

**Atenção:** SSR e bomba estão habilitados em config.json no modo bench. A fervura física usa janela de 10 segundos e só pode iniciar após confirmação manual; a potência é zerada acima da referência. Não é um controlador certificado de segurança. Use corte térmico e contator independentes, valide polaridade e não faça o primeiro teste com a resistência conectada. A bomba é desligada em pausa, aviso pendente, falha e término. Comando manual da bomba prevalece até mudança de fase.

Atualização: instale em pasta nova e, com a versão anterior parada, copie receitas/, dados/ e seu config.json. Não copie os arquivos do programa antigo. Execute python3 beergo.py.

## Correção da referência de fervura (0.11Beta revisão 1)
A Fase Atual exibe a referência global da fervura como temperatura-alvo. A API de estado expõe `current_target_c` e as novas amostras do gráfico usam a referência vigente, inclusive quando alterada durante a execução. A receita BeerXML original não é modificada.


## Revisão 3 — disposição da coluna direita
- Bomba e Resistência da Panela lado a lado; Etapas da receita abaixo ocupando as duas colunas.
- Campo Potência atual (comando): percentual correspondente ao comando do SSR naquele instante (0% desligado; 100% na mostura ligado; percentual configurado na janela ativa de fervura). Não é potência elétrica medida nem estimativa do consumo.
- Mantidas as caixas centrais e os comandos existentes.


## Revisão 4 — gráfico otimizado
- Retirada somente a caixa central duplicada «Etapas da receita», abaixo do gráfico.
- Preservada a caixa «Etapas da receita» da coluna direita.
- A área do gráfico aproveita a largura disponível e a altura útil da tela; o desenho considera a altura real do canvas.
- Mantidos sem alterações os comandos, GPIOs, API, receitas, histórico e configuração.
- Para atualizar: instalar em pasta nova e copiar `receitas/`, `dados/` e `config.json` da instalação em uso com o programa parado.


## Revisão 5 — Recirculação restrita à mostura
- Padrão para instalações novas: recirculação cíclica marcada, ligada por 180 min, descanso de 60 min, ligada durante o aquecimento marcada.
- Tempos apresentados em minutos na interface; armazenamento e cálculo internos continuam em segundos.
- Os padrões antigos só são migrados automaticamente quando os quatro parâmetros da bomba ainda coincidem exatamente com os padrões de fábrica da Revisão 4. Ajustes personalizados são preservados.
- A bomba e a recirculação só podem funcionar durante etapas de mostura (Mash-in/descansos e Mash-out); o bloqueio vale também para o botão manual. Lavagem, fervura e fases seguintes mantêm a bomba desligada.
- A opção 'Ligada no aquecimento' se aplica apenas ao aquecimento das etapas de mostura.
- Saídas físicas continuam desligadas na inicialização; teste primeiro sem carga conectada.


## Revisão 6 — Eixo Y compacto e tempos em segundos
- Reduzida a margem interna esquerda do gráfico de 49 para 31 px; rótulos do eixo Y ficam alinhados à direita, junto à área de plotagem, sem alterar curvas, faixas ou eixo do tempo.
- Bomba cíclica por padrão: 180 segundos ligada, 60 segundos em descanso; ligada no aquecimento somente nas etapas de mostura. Lavagem e fases posteriores permanecem bloqueadas.
- A interface mostra e grava os tempos em segundos, sem conversão para minutos.
- Instalações que ainda tenham exatamente os quatro valores de fábrica antigos (Revisão 4 ou Revisão 5) recebem os novos padrões; configurações personalizadas são preservadas.
- Não foram alterados os demais painéis, controles, GPIOs, receitas ou histórico.


## Revisão 7 — lavagem e pré-aquecimento
Ao concluir a última etapa de mostura (Mash-out, ou Mash-in quando não houver Mash-out), o processo entra em WASH_PENDING. A bomba desliga e o aquecimento inicia imediatamente para a referência global de fervura, com histerese e proteções existentes. O operador deve confirmar o término da lavagem para entrar na fase de fervura; a confirmação de fervura existente permanece obrigatória para iniciar sua contagem. Avançar fase não contorna a confirmação de lavagem. Pausar, interromper, falha de sensor e bloqueio manual desligam o aquecimento. Após reinicialização, permanece exigida recuperação manual sem reenergização automática.


## Revisão 8 — Espaçamento compacto
- Base: Revisão 7, sem alterações no Python, JavaScript, HTML ou configurações.
- Apenas CSS: reduz para cerca de 6 px os intervalos entre menu e monitor, blocos superiores, caixas centrais e caixas laterais; mantém pequeno respiro visual.
- Preserva gráfico, confirmações de lavagem, pré-aquecimento, regras da bomba e todas as ações existentes.


## Revisão 9 — Diagnóstico informativo
Página Sistema / Diagnóstico em seis caixas: sistema/Raspberry Pi, sensor T1, saídas e periféricos, segurança e motivos do estado, rede/interface, eventos recentes. Endpoint somente leitura `/api/diagnostics`. Sem novos comandos de GPIO ou testes físicos. CPU é exibida como carga média (não porcentagem), clientes conectados não são monitorados e a alimentação mostra “Não monitorada” quando `vcgencmd` não estiver disponível. Estado do GPIO é comando de software, não medição de tensão/corrente. As leituras e contadores de sensor referem-se à execução atual. Preservados monitor, configurações, receitas, histórico, controle de bomba e aquecimento.


## Revisão 10 — Diagnóstico em três colunas
Somente CSS: seis caixas em duas linhas de três em telas com largura suficiente. Em larguras abaixo de 1050 px, duas colunas; abaixo de 700 px, uma coluna. Eventos adaptados à largura de uma caixa. Não há alteração no HTML, JavaScript, Python, parâmetros, segurança ou Monitor de Brassagem.


## Teste de layout sobre a REV10 funcional
Somente web/app.css foi alterado no aplicativo. O seletor usado é
`#monitor.page:not(.hidden)`, correspondente ao HTML real da REV10.
A partir de 1050 px: Fase Atual (aprox. 57%), Bomba e Resistência
(aprox. 21,5% cada), gráfico abaixo das duas primeiras e Etapas abaixo
da Resistência. Abaixo de 1050 px, mantém o layout original da REV10.
Valide primeiro o menu e os cinco botões no Raspberry Pi. Não substitua
a pasta da REV10 funcional durante o teste.

## Ajuste pontual do gráfico
O gráfico ocupa apenas a coluna 1, diretamente abaixo da Fase Atual,
com largura igual e altura de 190 px nas duas caixas. A coluna 2 da
segunda linha permanece vazia. A caixa Etapas da receita não foi alterada.
Somente CSS e README diferem do teste anterior.


## Ajuste pontual de espaçamento
O intervalo entre Fase Atual e Evolução da temperatura foi fixado em
6 px, igual ao intervalo usado entre Bomba e Resistência. A margem
inferior adicional da Fase Atual foi removida somente no layout de três
colunas. Nenhuma outra caixa, botão, menu ou lógica foi alterada.


## Caixa Data e tempo da brassagem (teste)
No espaço reservado na segunda coluna, ao lado do gráfico, foi adicionada
uma caixa com data e horário atuais do navegador, horário de início da
brassagem vindo do estado persistido e tempo decorrido desde o início.
Durante pausa/recuperação o tempo decorrido é tempo de relógio (não apenas
tempo ativo). Sem brassagem em andamento, o campo tempo decorrido mostra —.
A caixa tem a mesma largura e acompanha a altura da caixa Etapas da receita.
A lógica de controle, os comandos e a navegação não foram alterados.


## Ajuste de espaço entre Fase Atual e gráfico
A área principal usa agora uma coluna vertical independente: Fase Atual
seguida imediatamente pelo gráfico, com intervalo de 6 px. As caixas da
direita permanecem em grade de duas colunas, sem determinar a posição
vertical do gráfico. Somente `web/app.css` foi alterado no aplicativo.
Nenhum botão, menu, HTML, JavaScript, Python ou configuração foi modificado.


## Gráfico alinhado ao relógio — teste
O gráfico mantém seu início a 6 px abaixo de Fase Atual e passa a
estender-se até a borda inferior da caixa Data e tempo da brassagem.
As caixas da direita mantêm posição e dimensões. O desenho do gráfico
agora respeita a altura real do canvas, evitando recorte dos eixos em
alturas inferiores a 300 px. Nenhum comando, menu, Python ou configuração
foi modificado. Conferir o alinhamento visual no Raspberry Pi.

## Alinhamento dinâmico do gráfico (teste)
O gráfico mantém o início 6 px abaixo de Fase Atual. Sua altura é calculada
a partir da borda inferior mais baixa de Data e tempo da brassagem e Etapas
da receita, ambas com altura natural determinada pelo conteúdo. O cálculo
é refeito após a atualização da interface, mudanças de tamanho das caixas
e redimensionamento da janela. Não altera navegação, botões ou controlador.


## Área útil do gráfico ampliada
Ocultada somente a legenda de cores acima do gráfico (Temperatura,
Mash Out, Fervura e demais fases). Removidas as legendas de linha
Temperatura/Alvo e os textos Início/Agora desenhados no canvas.
Margens internas superior/inferior do desenho reduzidas de 30/38 px
para 8/8 px. Os valores do eixo Y, as curvas, os alvos e as faixas
coloridas continuam sendo desenhados. O alinhamento dinâmico inferior
e a posição das demais caixas são preservados.

## Revisão experimental: diálogos em português
A baseline aprovada `BeerGoPi_REV10_TESTE_GRAFICO_AREA_AMPLIADA` permanece intacta.
Esta revisão substitui os `confirm()` do navegador nas ações de avanço, conclusão, interrupção, exclusão de receita/histórico e desligamento manual do aquecimento por diálogos visuais próprios. Tradução visual dos estados na caixa Fase Atual. Sem alterações no Python, nas rotas da API, no GPIO, nas receitas ou nas configurações. Mensagens de rotina continuam não bloqueantes.


## Teste: ícones da Fase Atual
Base: BeerGoPi_REV10_TESTE_MODAIS_PTBR. Apenas os cinco botões da Fase Atual
foram convertidos em ícones circulares com tooltip no mouse/foco. Os IDs,
onclick, regras de habilitação e confirmações permanecem inalterados.
O botão Pausar alterna para Recomeçar no estado PAUSED. Não altera dimensões
da caixa, demais cartões, Python ou configuração. Validar no Raspberry Pi.


## Revisão experimental: ícones das etapas da brassagem
A faixa de etapas da Receita atual recebeu seis ícones vetoriais locais
(Aquecimento, Mostura, Lavagem, Fervura, Resfriamento e Concluído).
A etapa em andamento é realçada; etapas anteriores recebem indicação
discreta de conclusão. A identificação de lavagem pendente foi incluída
no destaque. A geometria da caixa e o backend não foram modificados.

## Revisão experimental: etapas ilustradas
Substituídos os SVG simplificados por recortes das seis ilustrações aprovadas,
embutidos como WebP no CSS. Os nomes são exibidos somente ao passar o mouse
ou focar pelo teclado. A etapa em andamento recebe brilho; etapas anteriores
continuam identificadas. Mantidas as dimensões da caixa Receita Atual,
a lógica do processo, os controles e o backend da revisão anterior.


## Revisão experimental: confirmações de lavagem e fervura
Os botões contextuais de término de lavagem e início de fervura agora usam
as mesmas janelas modais estilizadas das demais confirmações. Cancelar,
fechar ou pressionar Escape não envia comando; apenas Confirmar envia
a solicitação original ao backend. Os comandos, endpoints e backend
permanecem inalterados.


## Tradução geral da interface (teste)
Traduzidos os estados COUNTDOWN/INTERRUPTED e demais estados conhecidos na Fase Atual, no diagnóstico e nos eventos do histórico e diagnóstico. Os campos Mash/Sparge/Boil das adições passam a ser apresentados como Mostura/Lavagem/Fervura. Erros brutos do sensor recebem uma descrição em português, com o detalhe técnico original preservado. Nomes de etapas definidos pelo BeerXML, nomes de arquivos, identificadores de GPIO/SSR e valores de protocolo não foram alterados. Backend, configuração e registros originais permanecem intactos.


## Pop-ups contextuais sem duplicidade
Ao entrar em término de lavagem ou confirmação de fervura, a interface
abre automaticamente o pop-up estilizado, sem mostrar simultaneamente
o botão fixo de confirmação. Cancelar/Esc não envia comando nem avança
a etapa; somente depois de cancelar aparece o botão discreto para
reabrir a confirmação pendente. A lógica de processo e o backend
permanecem inalterados.


## Eixo X do gráfico de temperatura
Marcações de horário local no formato HH:MM.SS, com intervalos
adaptativos ao período das amostras e à largura efetiva do canvas.
A largura do texto é medida antes de desenhar cada rótulo, evitando
sobreposição e cortes nas bordas. Reserva inferior de 30 px para o
eixo X, sem alterar a altura externa do gráfico nem das caixas.
A lógica de controle e o backend não foram modificados.

## Ajuste do gráfico
Removida a frase informativa sob o gráfico ('Amostras a cada 5 segundos; áreas coloridas indicam as fases.') e o espaço que ocupava. Mantidas as marcações HH:MM.SS no eixo X, o alinhamento dinâmico e as demais funções.


## PID experimental da mostura (opt-in)
A configuração PID está DESLIGADA por padrão. Ative somente após
verificar o sensor real, a circulação, o contator de segurança e o
desligamento físico do SSR. Parâmetros iniciais provisórios: Kp=8,
Ki=0,03 e Kd=0; NÃO são parâmetros calibrados para a panela.
O controlador ajusta a fração ligada em janelas de 10 s somente na
mostura; lavagem e fervura preservam o controle anterior. Há limitação
de integral, derivada sobre a medição, reset ao sair da operação e
corte de aquecimento a partir de 1,5 °C acima do alvo. O PID não
realiza autotuning e não altera os parâmetros sozinho. Não usar
sem supervisão em testes reais; a proteção física independente é
obrigatória. Os dados existentes e a baseline anterior são preservados.

## Caixa Resistência da Panela
A ordem visual é: Comando de aquecimento, Controle térmico, Potência atual, Parâmetro.
O modo PID selecionado aparece como PID (mostura), pois lavagem/fervura preservam o controle anterior.
Parâmetro exibe Kp, Ki e Kd no PID ou Graus (°C) na histerese. Potência atual é
a solicitação calculada ao SSR, não medição elétrica. Não houve alteração das dimensões
da caixa, dos parâmetros salvos ou da lógica de acionamento.

## Identidade visual BeerGoPi
Logo BeerGoπ com ramos de lúpulo verdes, arquivo PNG original 2172 × 724 pixels (sem redimensionar/recomprimir). O cabeçalho mantém as dimensões CSS anteriores; somente o arquivo exibido e o limite de largura legado foram alterados. A baseline do controle, PID, telas e dados permanece inalterada.

## Correção da rota do logo
O servidor HTTP agora disponibiliza /beergo-pi-logo-lupulo.png (antes retornava 404 e o navegador exibia o texto alternativo). Imagem, layout, lógica de controle e demais arquivos preservados.

## Identidade visual — logo abaulado transparente
Imagem BeerGoπ aprovada pelo usuário, com abaulamento invertido e ramos de lúpulo, PNG RGBA com fundo realmente transparente (2172 × 724). Substituído apenas web/beergo-pi-logo-lupulo.png; HTML, CSS, JS e backend permanecem iguais à versão de rota corrigida.


## Acesso pela rede local
O servidor escuta em 0.0.0.0:18765 (todas as interfaces do Raspberry Pi). No navegador de outro dispositivo da mesma rede, use http://IP_DO_RASPBERRY:18765. Não encaminhe a porta no roteador para a internet. Ao atualizar uma instalação existente, preserve seu config.json ou altere somente a chave "host" para "0.0.0.0"; substituir o arquivo pode sobrescrever configurações locais. Reinicie o serviço após a alteração.


## Ajustes visuais das etapas e do cabeçalho
- Ilustrações das seis etapas centralizadas no próprio espaço, sem mudar a geometria das caixas.
- Quando não há brassagem em andamento (IDLE, STOPPED, INTERRUPTED, COMPLETE, FAULT), nenhum ícone fica realçado ou marcado como concluído. Uma execução pausada mantém o contexto da etapa.
- Cabeçalho mostra somente `0.11Beta` em letras pequenas após o logo, sem os textos BeerGoPi/IHC/Supervisor Produção. A versão interna do backend não foi modificada.
- Configuração de rede local, PID e logo transparente preservados.


## Mobile tela única — teste isolado
A página /mobile usa a altura útil do celular sem rolagem, com SVG da panela única,
cesto de malte, saída no fundo, bomba e retorno sobre o cesto. O fluxo animado
e a resistência refletem os comandos reais de telemetria; em caso de perda de
comunicação as animações param. Toques na figura e nos indicadores exibem apenas
detalhes locais; o mobile envia somente GET a /api/mobile/state.
Atenção: somente leitura na tela NÃO bloqueia o acesso ao painel operacional /
nem às suas APIs pela mesma rede. Autenticação/autorização exigem etapa própria.
Instale preservando seus arquivos de dados e configurações existentes.


## Figura mobile inspirada no vídeo (experimental)
Revisão exclusivamente visual de `/mobile`: panela alta de inox, alças, saída inferior com registro, bomba externa de corpo verde, mangueira transparente com retorno curvado por cima da borda e caixa controladora branca separada com três interruptores e visor. O cesto foi desenhado esquematicamente, pois não está visível instalado no vídeo. O SVG mantém a animação condicionada à telemetria e os detalhes locais somente leitura. Não foram alterados backend, rotas, tela desktop nem configurações.


## Revisão mobile: sparge e avisos somente leitura
A mangueira sai da bomba, sobe à borda, conecta-se ao pequeno tubo horizontal e ao sparge. O corpo da bomba não gira nem se desloca; o fluxo anima somente dentro das tubulações e no retorno. A rota GET `/api/mobile/state` agora inclui somente os dados dos avisos pendentes e mensagem de estado; não há novos comandos. O mobile mostra avisos de adição, lavagem, fervura, recuperação e sensor como notificações locais de leitura. Fechar um aviso no celular não o confirma no BeerGoPi. Os avisos são derivados do estado atual e não reproduzem necessariamente todas as mensagens transitórias exibidas apenas no navegador principal. A autenticação do painel operacional permanece fora do escopo.


## Interface mobile com imagem aprovada (experimental)
A imagem `web/mobile-setup-aprovado.png` é exatamente a imagem aprovada pelo usuário, sem redesenho. A tela sobrepõe dados reais e efeitos SVG à imagem. As leituras ilustrativas impressas no PNG são cobertas por indicadores dinâmicos; alguns detalhes puramente decorativos da imagem permanecem estáticos. A barra de progresso é deixada em zero quando o backend não fornece duração total da etapa, evitando inventar porcentagem. A animação da tubulação é uma sobreposição aproximada à geometria do PNG, não uma transformação do PNG em vídeo. Avisos são somente informativos; confirmação permanece no painel principal. Nenhuma requisição POST é enviada pelo mobile. A tela operacional e APIs continuam acessíveis na rede sem autenticação: a página de leitura não é uma barreira de segurança.


## Revisão experimental: pop-ups de adições
Adições pendentes de sais e lúpulos abrem pop-up no monitor desktop.
Fechar ou cancelar NÃO confirma adição: a pendência permanece no painel, com seu botão original.
A confirmação só é enviada após clique explícito do operador. O mobile e a imagem aprovada
permanecem idênticos à baseline. A alteração visual da resistência e dos tubos
não integra este pacote e requer edição da imagem aprovada sem alterar sua composição.


## Correção experimental: transição automática Mash In → Mash Out
Ao terminar o tempo de uma etapa de mostura, se a próxima etapa BeerXML também for de mostura, a transição ocorre automaticamente e inicia o aquecimento para o novo alvo. A passagem da última etapa de mostura para a lavagem permanece com o comportamento anterior. Avisos pendentes continuam bloqueando o avanço até confirmação operacional. Esta versão parte do pacote experimental POPUPS_ADICOES_TESTE; a baseline mobile aprovada não foi substituída.


## Estados visuais da figura aprovada — teste
A imagem mobile-setup-aprovado.png permanece byte a byte idêntica à baseline.
Foi acrescentada uma camada SVG sobre a imagem para ocultar os elementos
alaranjados incorporados à ilustração quando a bomba e/ou resistência estão
desligadas. Com bomba desligada, os tubos são cobertos por representação
metálica sem fluxo e o sparge deixa de mostrar spray; com resistência desligada,
o elemento aparece prateado. Comando ativo revela a figura aprovada e seus
efeitos animados. Se a telemetria falhar, a página volta ao estado visual
desligado. Este é um ajuste de apresentação, NÃO uma leitura do estado elétrico
físico dos equipamentos. Validar o alinhamento das camadas no celular.
Backend, pop-ups de adições e Mash Out automático preservados.


## Revisão mobile/logo e PID padrão
- Mantida byte a byte a imagem aprovada. Removida a camada SVG de estados
  desligados: a imagem continua com líquido e resistência original; somente
  as animações de fluxo e aquecimento dependem da telemetria.
- Faixa inferior com ícones da bomba, resistência e termômetro recortada da
  apresentação; logo BeerGoπ original acima do setup. A página continua sem
  rolagem e os toques nos componentes preservam os detalhes de leitura.
- PID é o padrão SOMENTE para novas instalações sem dados/configuracoes.json.
  Instalações existentes preservam a escolha PID/histerese já gravada; para
  ativar PID nelas, selecionar PID em Configurações e salvar. Isso evita
  alterar silenciosamente a opção operacional previamente persistida.
- PID experimental mantém os ganhos anteriores (Kp 8.0, Ki 0.03, Kd 0.0).
  Validar comportamento térmico com supervisão antes de operação autônoma.
- Pop-ups de adições e Mash Out automático permanecem inalterados.


## Ajuste responsivo mobile — teste
A página usa 100dvh e áreas seguras do celular. O logo original cresce na
região disponível acima do setup; a figura aprovada mantém sua proporção
1024:1250 (recorte apenas da antiga faixa inferior), preservando o alinhamento
das sobreposições e áreas de toque. Em paisagem, logo e setup ficam lado a
lado. A barra de endereço do navegador não é ocultada por CSS.
Nenhuma alteração no backend, PID, pop-ups ou Mash Out automático.


## Fervura automática e potência no mobile — TESTE
- A etapa de fervura aquece até a referência configurada pelo usuário.
  Ao atingir o alvo, o cronômetro começa automaticamente, sem confirmação.
  A duração não é debitada no ciclo de leitura que atinge o alvo.
- A API antiga de confirmação manual de fervura rejeita o comando, impedindo
  que clientes desatualizados iniciem a contagem prematuramente.
- O mobile exibe SSR ON/OFF e, abaixo, potência solicitada (%) da etapa.
  O percentual é comando de controle, NÃO medição de consumo elétrico.
- A imagem aprovada, os pop-ups de sais/lúpulos, o Mash Out automático e
  o PID padrão em novas instalações são preservados.
- ATENÇÃO: testar no modo de bancada/simulação antes de brassagem real.
