#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gera um livro (HTML + PDF) com capa clara, sumário, cabeçalho/rodapé e EXATAMENTE 80 páginas.
- Saídas:
  - ./saida/livro.html
  - ./saida/livro.pdf

Dependência para PDF:
  pip install xhtml2pdf
  
Nota: Tenta usar WeasyPrint primeiro (melhor qualidade), mas se falhar no Windows,
      usa xhtml2pdf automaticamente (funciona sem bibliotecas do sistema).
"""

from __future__ import annotations
import os
from datetime import date


# =========================
# CONFIGURAÇÃO DO LIVRO
# =========================
BOOK_TITLE = "O CÓDIGO DA CONEXÃO"
BOOK_SUBTITLE = "Psicologia, Conversação e Presença para Atração Natural"
AUTHOR = "Jeferson Fortunato"
TODAY = date.today().strftime("%d/%m/%Y")

# 16 capítulos
CHAPTERS = [
    "A Base da Atração Humana",
    "O Poder da Presença",
    "Leitura Psicológica do Interesse",
    "Linguagem Corporal e Micro-Sinais",
    "Conversação de Alto Nível",
    "Frases que Criam Curiosidade",
    "Conexão Emocional Profunda",
    "A Arte de Ser Memorável",
    "Reciprocidade e Consistência",
    "Limites e Ética (Contexto do Trabalho)",
    "Criando Interesse Sem Forçar",
    "Confiança Silenciosa",
    "Admiração no Longo Prazo",
    "Erros que Rompem Conexão",
    "Diálogos Práticos",
    "O Código Final",
]

# Orçamento de páginas por capítulo (para garantir 80 páginas exatas)
# Capítulos 1-12: 5 páginas cada = 60 páginas
# Capítulos 13-16: 4 páginas cada = 16 páginas
# Total capítulos = 76 páginas
# + 1 capa + 1 sumário + 1 intro + 1 conclusão = 80 páginas
CHAPTER_PAGE_BUDGET = [5] * 12 + [4] * 4

OUTPUT_DIR = "saida"
HTML_NAME = "livro.html"
PDF_NAME = "livro.pdf"


# =========================
# UTILITÁRIOS
# =========================
def escape_html(s: str) -> str:
    """Escapa caracteres HTML."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def p_tag(text: str) -> str:
    """Cria uma tag <p>."""
    return f"<p>{escape_html(text)}</p>"


def h2_tag(text: str) -> str:
    """Cria uma tag <h2>."""
    return f"<h2>{escape_html(text)}</h2>"


def ul_tag(items: list[str]) -> str:
    """Cria uma tag <ul> com itens."""
    lis = "".join(f"<li>{escape_html(item)}</li>" for item in items)
    return f"<ul>{lis}</ul>"


# =========================
# CONTEÚDO DOS CAPÍTULOS
# =========================

# Capítulo 1 - Conteúdo detalhado
CHAPTER_1_CONTENT = {
    "visao_geral": [
        "A atração humana não é um jogo de técnicas ou scripts. É um fenômeno natural que surge quando há segurança emocional, presença autêntica e compatibilidade genuína.",
        "Este capítulo explora os cinco pilares fundamentais que sustentam qualquer conexão duradoura e saudável entre pessoas.",
    ],
    "ideias_chave": [
        "Segurança emocional: previsibilidade saudável, sem jogos, sem pressão. A outra pessoa precisa sentir que você é confiável e respeitoso.",
        "Presença: atenção real, escuta ativa, voz calma, pausas naturais. Quando você está presente, a outra pessoa se sente vista e valorizada.",
        "Compatibilidade: valores, objetivos e visão de vida alinhados. Não é sobre ser igual, mas sobre complementar-se de forma harmoniosa.",
        "Valor percebido: não é sobre status ou aparência, mas sobre quem você é: responsabilidade, caráter, disciplina, calma. Isso gera admiração.",
        "Timing: conexões profundas não podem ser forçadas. Respeite o ritmo natural da outra pessoa e o contexto da situação.",
    ],
    "aplicacao": [
        "Atração não é performance. Você não precisa impressionar a cada momento. Na verdade, tentar impressionar demais pode gerar o efeito contrário: ansiedade e insegurança.",
        "O que realmente funciona é consistência: ser a mesma pessoa respeitosa, presente e autêntica em diferentes contextos. Isso cria segurança emocional.",
        "Quando você para de tentar 'conquistar' e começa a 'conectar', tudo muda. A pressão desaparece, a naturalidade aparece e a conexão flui.",
        "Observe como você se sente na presença da outra pessoa. Se você se sente bem, relaxado e autêntico, provavelmente ela também se sente assim com você.",
        "A atração saudável aumenta quando você não força. Clareza e leveza funcionam melhor do que pressão. Se houver abertura, o avanço acontece naturalmente.",
        "No longo prazo, o que sustenta é admiração: responsabilidade, caráter, disciplina e calma. Isso gera segurança — e segurança é magnética.",
        "Uma conexão forte raramente acontece por frases bonitas. Ela cresce quando há presença: atenção real, escuta sem pressa e atitude madura.",
        "A melhor leitura emocional vem de padrão, não de evento isolado. Observe repetição, contexto e reciprocidade antes de concluir qualquer coisa.",
    ],
    "exercicios": [
        "Escolha 1 conversa do dia e diminua o ritmo (responda 2 segundos mais devagar). Observe como isso muda a dinâmica.",
        "Faça 1 pergunta aberta de valores (futuro, objetivos, visão de vida). Escute sem interromper.",
        "Anote 3 fatos do dia sem interpretação (treino de leitura emocional). Pratique observar sem julgar.",
        "Pratique um convite leve com opção real de recusa. Respeite a resposta, seja qual for.",
    ],
    "frases": [
        "\"Curti conversar com você hoje.\"",
        "\"Você tem um jeito interessante de ver as coisas.\"",
        "\"Fala mais — eu quero entender teu ponto.\"",
        "\"Sem pressa… a gente resolve isso com calma.\"",
        "\"Se você topar, qualquer dia a gente toma um café.\"",
    ],
    "checklist": [
        "Falei com calma e sem ansiedade?",
        "Fui respeitoso(a) com o tempo e o espaço do outro?",
        "Houve reciprocidade real (iniciativa, atenção, investimento)?",
        "Eu mantive meu valor (rotina, postura, autocontrole)?",
    ],
    "resumo": [
        "Os cinco pilares da atração humana — segurança emocional, presença, compatibilidade, valor percebido e timing — não são técnicas, mas fundamentos de comunicação madura.",
        "Quando você para de tentar impressionar e começa a conectar de forma autêntica, a atração surge naturalmente. A consistência é mais poderosa que a performance.",
        "Pratique presença, escuta ativa e respeito ao ritmo da outra pessoa. A conexão profunda não pode ser forçada, mas pode ser cultivada com paciência e autenticidade.",
    ],
}

# Capítulo 2 - Conteúdo detalhado
CHAPTER_2_CONTENT = {
    "visao_geral": [
        "Presença não é sobre o que você diz, mas sobre como você está. É a qualidade da sua atenção, a calma da sua voz, a segurança da sua postura.",
        "Quando você está verdadeiramente presente, a outra pessoa sente. Não há necessidade de palavras elaboradas — sua presença comunica mais do que qualquer frase.",
    ],
    "ideias_chave": [
        "Corpo fala: postura ereta mas relaxada, respiração profunda e regular. Evite gestos ansiosos ou inquietação. Seu corpo comunica confiança quando está calmo.",
        "Voz: ritmo mais lento que o normal, pausas naturais entre frases. Não tenha medo do silêncio — ele cria espaço para a outra pessoa pensar e responder.",
        "Olhar: contato visual natural, sem interrogatório. Olhe nos olhos quando fala e quando escuta, mas não fixe de forma intensa ou desconfortável.",
        "Pausas como ferramenta: após fazer uma pergunta ou fazer uma afirmação, faça uma pausa. Isso demonstra confiança e dá espaço para a outra pessoa processar.",
        "Respiração: quando você respira profundamente, seu sistema nervoso se acalma. Isso se reflete na sua voz e na sua postura, criando uma presença mais forte.",
    ],
    "aplicacao": [
        "Antes de uma conversa importante, reserve 2 minutos para respirar profundamente. Isso acalma o sistema nervoso e aumenta sua presença.",
        "Pratique falar 20% mais devagar que seu ritmo normal. Isso não só aumenta sua presença, mas também melhora sua clareza e impacto.",
        "Use pausas estratégicas: após uma pergunta, após uma afirmação importante, ou quando a outra pessoa está processando algo. O silêncio é poderoso.",
        "Mantenha uma postura aberta: ombros relaxados, peito aberto, braços não cruzados. Isso comunica abertura e confiança.",
        "Quando você está presente, você escuta melhor. E quando você escuta melhor, você responde de forma mais relevante e conectada.",
        "A presença é contagiosa: quando você está calmo e presente, a outra pessoa tende a relaxar também. Isso cria um ambiente de conexão.",
        "Evite distrações: desligue notificações, mantenha o telefone longe, dê atenção total à conversa. A presença exige atenção total.",
        "Pratique presença mesmo em conversas casuais. Quanto mais você pratica, mais natural se torna.",
    ],
    "exercicios": [
        "Pratique respirar profundamente 5 vezes antes de iniciar uma conversa importante.",
        "Em uma conversa, conte mentalmente até 3 antes de responder. Observe como isso muda a qualidade da sua resposta.",
        "Pratique fazer uma pausa de 3 segundos após fazer uma pergunta. Observe a reação da outra pessoa.",
        "Grave sua voz em uma conversa casual. Depois, ouça e identifique onde você poderia ter feito pausas ou falado mais devagar.",
    ],
    "frases": [
        "\"Deixa eu pensar um momento...\" (pausa natural)",
        "\"Isso é interessante. Fala mais sobre isso.\"",
        "\"Entendi. E como você se sentiu com isso?\"",
        "\"Não tenho pressa. A gente pode conversar com calma.\"",
        "\"Quero entender melhor seu ponto de vista.\"",
    ],
    "checklist": [
        "Minha postura estava relaxada mas ereta?",
        "Falei com ritmo calmo e fiz pausas naturais?",
        "Mantive contato visual confortável?",
        "Escutei mais do que falei?",
    ],
    "resumo": [
        "Presença é a qualidade da sua atenção e da sua calma. Quando você está presente, sua postura, voz e olhar comunicam confiança e abertura.",
        "Pratique respirar profundamente, falar mais devagar e usar pausas estratégicas. A presença é uma habilidade que se desenvolve com prática constante.",
        "A presença é contagiosa: quando você está calmo e presente, a outra pessoa tende a relaxar também, criando um ambiente propício para conexão.",
    ],
}

# Capítulo 3 - Conteúdo detalhado
CHAPTER_3_CONTENT = {
    "visao_geral": [
        "Ler interesse real não é sobre interpretar cada gesto ou palavra isoladamente. É sobre observar padrões, contexto e reciprocidade ao longo do tempo.",
        "Este capítulo ensina a distinguir entre sinais genuínos de interesse e comportamentos que são apenas educação ou cortesia.",
    ],
    "ideias_chave": [
        "Padrões vs episódios: um evento isolado não significa nada. Observe repetição: a pessoa busca sua presença? Inicia conversas? Investe tempo?",
        "Atenção seletiva: quando há interesse real, a pessoa prioriza você. Ela responde mensagens, faz tempo para conversar, lembra de detalhes que você mencionou.",
        "Investimento: interesse real se manifesta através de investimento — tempo, atenção, cuidado, iniciativa. Se só você investe, não há reciprocidade.",
        "Cuidados: não confundir educação com interesse. Ser educado é diferente de buscar conexão. Observe se há iniciativa além da cortesia básica.",
        "Contexto importa: o mesmo comportamento pode significar coisas diferentes em contextos diferentes. Considere o ambiente, a relação e a situação.",
    ],
    "aplicacao": [
        "Observe padrões, não eventos isolados. Uma pessoa pode sorrir por educação, mas se ela busca sua presença repetidamente, isso é um padrão significativo.",
        "Atenção seletiva é um sinal forte: quando alguém tem interesse, ela prioriza você. Ela responde rápido, faz tempo para conversar, lembra de detalhes.",
        "Investimento é recíproco: se você é o único que inicia conversas, faz convites ou investe tempo, provavelmente não há interesse real do outro lado.",
        "Não confunda educação com interesse. Ser educado, responder mensagens ou ser cortês são comportamentos básicos de convivência, não sinais de interesse.",
        "Observe iniciativa: pessoas interessadas tomam iniciativa. Elas fazem perguntas, compartilham coisas sobre si, buscam sua presença de forma ativa.",
        "Contexto importa: o mesmo comportamento pode significar coisas diferentes. Uma pessoa pode ser mais reservada no trabalho, mas mais aberta em contextos sociais.",
        "Reciprocidade é a chave: interesse real se manifesta através de reciprocidade. Se você investe e não recebe investimento de volta, ajuste suas expectativas.",
        "Paciência: leitura emocional requer tempo. Não tire conclusões precipitadas. Observe padrões ao longo de dias ou semanas, não em uma única interação.",
    ],
    "exercicios": [
        "Anote 3 interações da semana sem interpretação. Apenas fatos: quem iniciou, quanto tempo durou, o que foi dito (sem análise).",
        "Observe padrões: a pessoa busca sua presença? Inicia conversas? Investe tempo? Anote por 1 semana.",
        "Pratique distinguir educação de interesse: liste 3 comportamentos que podem ser apenas educação vs 3 que indicam interesse real.",
        "Reflita: há reciprocidade real? Você investe e recebe investimento de volta? Seja honesto consigo mesmo.",
    ],
    "frases": [
        "\"Você parece estar ocupado(a). Quando tiver um tempinho, a gente conversa.\"",
        "\"Curti nossa conversa. Se quiser continuar depois, estou por aqui.\"",
        "\"Não quero te incomodar. Se você tiver interesse, me avisa.\"",
        "\"Observo que você tem estado ocupado(a). Tudo bem por aí?\"",
        "\"Se você quiser conversar, estou disponível. Sem pressão.\"",
    ],
    "checklist": [
        "Observei padrões, não apenas eventos isolados?",
        "Identifiquei reciprocidade real (investimento de ambos os lados)?",
        "Não confundi educação com interesse?",
        "Considerei o contexto da situação?",
    ],
    "resumo": [
        "Ler interesse real requer observar padrões, não eventos isolados. Atenção seletiva, investimento recíproco e iniciativa são sinais mais confiáveis que gestos ou palavras isoladas.",
        "Não confunda educação com interesse. Ser educado é diferente de buscar conexão. Observe se há iniciativa além da cortesia básica.",
        "Paciência e observação são essenciais. Leitura emocional precisa de tempo para identificar padrões consistentes ao longo de dias ou semanas.",
    ],
}

# Conteúdo específico para capítulos 4-16
def get_chapter_content(chapter_num: int, chapter_title: str) -> dict:
    """Retorna conteúdo específico e único para cada capítulo."""
    
    # Capítulo 4: Linguagem Corporal e Micro-Sinais
    if chapter_num == 4:
        return {
            "visao_geral": [
                "A linguagem corporal comunica mais do que palavras. Micro-sinais — pequenos gestos, expressões faciais e mudanças sutis na postura — revelam estados emocionais e níveis de interesse que as palavras podem esconder.",
                "Este capítulo ensina a ler e usar a linguagem corporal de forma ética, sem invadir o espaço pessoal ou criar desconforto.",
            ],
            "ideias_chave": [
                "Espelho natural: quando há conexão, as pessoas tendem a espelhar postura e gestos. Observe se há sincronização sutil.",
                "Proximidade: pessoas interessadas reduzem inconscientemente a distância física. Respeite sempre o espaço pessoal.",
                "Contato visual: olhar direto e confortável indica abertura. Evite olhar fixo ou evasivo — busque o equilíbrio.",
                "Gestos abertos: braços abertos, palmas visíveis e postura relaxada indicam conforto. Braços cruzados podem indicar defesa.",
                "Micro-expressões: mudanças rápidas na expressão facial (frações de segundo) revelam emoções genuínas antes da máscara social.",
            ],
            "aplicacao": [
                "Observe espelhamento: se a pessoa espelha sua postura ou gestos, há provável conexão. Não force o espelhamento — deixe acontecer naturalmente.",
                "Respeite zonas de proximidade: aproxime-se gradualmente e observe a resposta. Se houver recuo, mantenha distância.",
                "Pratique contato visual confortável: olhe nos olhos ao falar e escutar, mas faça pausas naturais. 60-70% do tempo é ideal.",
                "Use gestos abertos: mantenha braços relaxados, palmas ocasionalmente visíveis. Evite gestos defensivos ou fechados.",
                "Leia micro-expressões com cuidado: uma expressão rápida de surpresa ou interesse pode ser significativa, mas não tire conclusões precipitadas.",
                "Observe mudanças: uma pessoa que estava tensa e depois relaxa na sua presença está se sentindo mais confortável.",
                "Evite interpretações excessivas: um único gesto não significa nada. Observe padrões ao longo do tempo.",
                "Use sua própria linguagem corporal: postura ereta mas relaxada, gestos calmos e presença física confiante comunicam segurança.",
            ],
            "exercicios": [
                "Pratique observar linguagem corporal: em 3 conversas, anote 2 gestos ou posturas que observou (sem interpretar).",
                "Pratique espelhamento natural: em uma conversa, sutilmente espelhe a postura da outra pessoa e observe a reação.",
                "Pratique contato visual: em uma conversa, mantenha contato visual 60-70% do tempo e observe como isso muda a dinâmica.",
                "Anote micro-sinais: durante uma semana, anote 1 micro-sinal por dia (expressão facial, gesto, mudança de postura) sem interpretar.",
            ],
            "frases": [
                "\"Percebi que você estava pensando... o que passou pela sua cabeça?\"",
                "\"Você parece confortável aqui. Isso é bom.\"",
                "\"Noto que você relaxou. Fico feliz com isso.\"",
                "\"Seu jeito de falar é interessante — você usa as mãos de forma expressiva.\"",
                "\"Posso me aproximar um pouco mais? Quero ouvir melhor.\"",
            ],
            "checklist": [
                "Observei a linguagem corporal sem invadir o espaço pessoal?",
                "Usei gestos abertos e postura confortável?",
                "Mantive contato visual natural (60-70% do tempo)?",
                "Não tirei conclusões precipitadas baseadas em um único gesto?",
            ],
            "resumo": [
                "A linguagem corporal comunica mais do que palavras. Micro-sinais revelam estados emocionais e níveis de interesse, mas devem ser lidos com cuidado e respeito.",
                "Pratique observar padrões, não eventos isolados. Use sua própria linguagem corporal para comunicar segurança e abertura.",
                "Respeite sempre o espaço pessoal. Aproxime-se gradualmente e observe a resposta. Conforto e conexão não podem ser forçados.",
            ],
        }
    
    # Capítulo 5: Conversação de Alto Nível
    elif chapter_num == 5:
        return {
            "visao_geral": [
                "Conversação de alto nível vai além do superficial. É sobre criar diálogos que exploram valores, experiências e visões de mundo, gerando conexão intelectual e emocional profunda.",
                "Este capítulo ensina técnicas para elevar a qualidade das conversas, tornando-as memoráveis e significativas.",
            ],
            "ideias_chave": [
                "Perguntas abertas: invés de \"como foi seu dia?\", pergunte \"o que te moveu hoje?\" ou \"o que você descobriu sobre si mesmo?\"",
                "Escuta ativa: não espere sua vez de falar. Escute para entender, não para responder. Faça perguntas de seguimento.",
                "Profundidade gradual: comece leve, aprofunde gradualmente. Não force temas pesados logo no início.",
                "Vulnerabilidade seletiva: compartilhe algo pessoal relevante para criar espaço para a outra pessoa fazer o mesmo.",
                "Temas universais: valores, sonhos, medos, aprendizados, visão de futuro — esses temas criam conexão profunda.",
            ],
            "aplicacao": [
                "Faça perguntas que exploram valores: \"O que é mais importante para você na vida?\" ou \"O que te faz sentir vivo?\"",
                "Use escuta ativa: repita o que ouviu para confirmar entendimento. \"Então você está dizendo que...\"",
                "Explore \"por quê\": quando alguém diz algo, pergunte \"por quê?\" para entender a motivação por trás.",
                "Compartilhe vulnerabilidade seletiva: \"Eu também já me senti assim quando...\" cria espaço para conexão.",
                "Evite perguntas de entrevista: \"onde você trabalha?\" é superficial. \"O que você ama no que faz?\" é profundo.",
                "Use silêncios estratégicos: após uma pergunta profunda, faça uma pausa. Dê tempo para a pessoa processar e responder.",
                "Conecte temas: \"Isso me lembra quando você mencionou...\" mostra que você escutou e está conectando pontos.",
                "Termine com reflexão: \"Essa conversa me fez pensar sobre...\" ou \"Obrigado por compartilhar isso comigo.\"",
            ],
            "exercicios": [
                "Pratique perguntas abertas: em 3 conversas, faça 1 pergunta que explore valores ou experiências profundas.",
                "Pratique escuta ativa: em uma conversa, repita o que ouviu 2 vezes para confirmar entendimento.",
                "Pratique vulnerabilidade seletiva: compartilhe 1 experiência pessoal relevante que crie espaço para conexão.",
                "Anote temas profundos: liste 5 temas que você gostaria de explorar em conversas (valores, sonhos, medos, etc.).",
            ],
            "frases": [
                "\"O que te move? O que realmente importa para você?\"",
                "\"Fala mais sobre isso — quero entender melhor.\"",
                "\"Isso me faz pensar... você já passou por algo parecido?\"",
                "\"Essa conversa está me fazendo refletir sobre coisas importantes.\"",
                "\"Obrigado por compartilhar isso. Significa muito.\"",
            ],
            "checklist": [
                "Fiz perguntas que exploram valores ou experiências profundas?",
                "Escutei ativamente, não apenas esperei minha vez de falar?",
                "Compartilhei vulnerabilidade seletiva para criar espaço de conexão?",
                "Evitei perguntas superficiais de entrevista?",
            ],
            "resumo": [
                "Conversação de alto nível explora valores, experiências e visões de mundo. Use perguntas abertas, escuta ativa e vulnerabilidade seletiva para criar conexão profunda.",
                "Profundidade vem gradualmente. Comece leve, aprofunde conforme a conexão se desenvolve. Não force temas pesados.",
                "Temas universais — valores, sonhos, medos, aprendizados — criam conexão intelectual e emocional que vai além do superficial.",
            ],
        }
    
    # Capítulo 6: Frases que Criam Curiosidade
    elif chapter_num == 6:
        return {
            "visao_geral": [
                "Curiosidade é o combustível da conexão. Quando você desperta curiosidade genuína na outra pessoa, ela quer saber mais sobre você, suas experiências e sua perspectiva.",
                "Este capítulo ensina como usar frases e técnicas que criam curiosidade de forma natural, sem parecer manipulação.",
            ],
            "ideias_chave": [
                "Abertura incompleta: \"Tenho uma história interessante sobre isso...\" cria curiosidade sem revelar tudo de uma vez.",
                "Contraste: \"A maioria das pessoas pensa X, mas eu descobri Y\" cria interesse pela perspectiva diferente.",
                "Mistério positivo: \"Algo interessante aconteceu hoje, mas não é hora de contar\" cria expectativa sem pressão.",
                "Perguntas reflexivas: \"Você já se perguntou por que...?\" convida a pessoa a pensar junto com você.",
                "Revelação gradual: compartilhe informações em camadas, não tudo de uma vez. Isso mantém a curiosidade.",
            ],
            "aplicacao": [
                "Use abertura incompleta: \"Tenho uma experiência interessante relacionada a isso, mas é uma história longa\" cria curiosidade natural.",
                "Crie contraste: \"A maioria das pessoas acha que X, mas minha experiência mostrou Y\" desperta interesse pela sua perspectiva.",
                "Use mistério positivo: \"Algo interessante aconteceu hoje, mas preciso processar antes de compartilhar\" cria expectativa respeitosa.",
                "Faça perguntas reflexivas: \"Você já se perguntou por que algumas conexões acontecem instantaneamente e outras levam tempo?\"",
                "Revele gradualmente: em vez de contar toda a história, compartilhe em partes. \"A primeira parte é...\"",
                "Use pausas estratégicas: após uma frase que cria curiosidade, faça uma pausa. Deixe a pessoa processar e querer saber mais.",
                "Conecte ao presente: \"Isso me lembra de algo que aconteceu...\" cria ponte entre o momento atual e uma história interessante.",
                "Termine com gancho: \"Mas isso é uma história para outro momento\" ou \"Talvez eu conte depois\" mantém a curiosidade viva.",
            ],
            "exercicios": [
                "Pratique abertura incompleta: em 2 conversas, use 1 frase que crie curiosidade sem revelar tudo.",
                "Pratique contraste: compartilhe 1 perspectiva diferente sobre um tema comum e observe a reação.",
                "Pratique perguntas reflexivas: faça 1 pergunta que convide a pessoa a pensar junto com você.",
                "Anote frases de curiosidade: liste 5 frases que você pode usar para criar curiosidade naturalmente.",
            ],
            "frases": [
                "\"Tenho uma história interessante sobre isso, mas é longa. Talvez outro dia.\"",
                "\"A maioria das pessoas pensa X, mas minha experiência foi diferente...\"",
                "\"Algo interessante aconteceu hoje, mas ainda estou processando.\"",
                "\"Você já se perguntou por que algumas conexões são instantâneas?\"",
                "\"Isso me lembra de algo, mas não é hora de contar. Talvez depois.\"",
            ],
            "checklist": [
                "Usei frases que criam curiosidade sem parecer manipulação?",
                "Criei contraste ou perspectiva diferente que desperta interesse?",
                "Fiz perguntas reflexivas que convidam a pensar junto?",
                "Revelei informações gradualmente, não tudo de uma vez?",
            ],
            "resumo": [
                "Curiosidade é o combustível da conexão. Use abertura incompleta, contraste, mistério positivo e perguntas reflexivas para criar interesse genuíno.",
                "Revelação gradual mantém a curiosidade viva. Compartilhe informações em camadas, não tudo de uma vez.",
                "Curiosidade deve ser natural, não forçada. Se parecer manipulação, perde o efeito. Pratique até soar autêntico.",
            ],
        }
    
    # Capítulo 7: Conexão Emocional Profunda
    elif chapter_num == 7:
        return {
            "visao_geral": [
                "Conexão emocional profunda vai além da atração física ou intelectual. É sobre criar um vínculo que toca o coração, onde ambas as pessoas se sentem vistas, compreendidas e valorizadas em um nível emocional.",
                "Este capítulo explora como desenvolver conexão emocional através de empatia, vulnerabilidade e presença emocional.",
            ],
            "ideias_chave": [
                "Empatia genuína: não apenas entender, mas sentir com a outra pessoa. \"Eu entendo como você se sente\" vs \"Eu também já me senti assim\".",
                "Vulnerabilidade mútua: quando você compartilha algo pessoal, cria espaço para a outra pessoa fazer o mesmo.",
                "Validação emocional: reconhecer e validar os sentimentos da outra pessoa, mesmo que você não concorde com a situação.",
                "Presença emocional: estar totalmente presente emocionalmente, não apenas fisicamente. Sentir junto, não apenas escutar.",
                "Memórias compartilhadas: criar momentos emocionais compartilhados que se tornam memórias significativas.",
            ],
            "aplicacao": [
                "Pratique empatia genuína: \"Eu entendo como você se sente. Eu também já passei por algo parecido\" cria conexão emocional.",
                "Compartilhe vulnerabilidade: \"Isso me tocou porque eu também já me senti assim quando...\" abre espaço para conexão profunda.",
                "Valide emoções: \"Faz sentido você se sentir assim\" ou \"Seus sentimentos são válidos\" mostra compreensão emocional.",
                "Use linguagem emocional: \"Como você se sentiu com isso?\" ou \"O que isso despertou em você?\" explora a dimensão emocional.",
                "Crie momentos compartilhados: \"Esse momento foi especial para mim também\" ou \"Vou lembrar dessa conversa\" cria memória emocional.",
                "Esteja presente emocionalmente: não apenas escute as palavras, mas sinta a emoção por trás delas. Responda à emoção, não apenas ao conteúdo.",
                "Use toque respeitoso (quando apropriado): um toque no braço ou ombro pode comunicar empatia e conexão, mas sempre com respeito e consentimento.",
                "Compartilhe impacto: \"Você me fez pensar sobre coisas importantes\" ou \"Essa conversa me tocou\" mostra o impacto emocional.",
            ],
            "exercicios": [
                "Pratique empatia genuína: em 2 conversas, valide os sentimentos da outra pessoa com \"Eu entendo como você se sente\".",
                "Pratique vulnerabilidade: compartilhe 1 experiência emocional pessoal que crie espaço para conexão profunda.",
                "Pratique presença emocional: em uma conversa, foque em sentir a emoção por trás das palavras, não apenas escutar.",
                "Anote momentos emocionais: liste 2 momentos compartilhados que criaram conexão emocional profunda.",
            ],
            "frases": [
                "\"Eu entendo como você se sente. Eu também já me senti assim.\"",
                "\"Seus sentimentos são válidos. Faz sentido você se sentir assim.\"",
                "\"Essa conversa me tocou. Obrigado por compartilhar isso comigo.\"",
                "\"Como você se sentiu com isso? O que isso despertou em você?\"",
                "\"Vou lembrar desse momento. Foi especial para mim também.\"",
            ],
            "checklist": [
                "Pratiquei empatia genuína, não apenas simpatia?",
                "Compartilhei vulnerabilidade que criou espaço para conexão?",
                "Validei os sentimentos da outra pessoa?",
                "Estive presente emocionalmente, não apenas fisicamente?",
            ],
            "resumo": [
                "Conexão emocional profunda requer empatia genuína, vulnerabilidade mútua e presença emocional. Vá além das palavras — sinta junto.",
                "Validação emocional mostra que você compreende e respeita os sentimentos da outra pessoa, mesmo que não concorde com a situação.",
                "Momentos compartilhados emocionalmente se tornam memórias significativas que fortalecem o vínculo ao longo do tempo.",
            ],
        }
    
    # Capítulo 8: A Arte de Ser Memorável
    elif chapter_num == 8:
        return {
            "visao_geral": [
                "Ser memorável não é sobre ser o mais bonito ou inteligente. É sobre criar impressões positivas duradouras através de momentos únicos, conversas significativas e presença autêntica.",
                "Este capítulo ensina como se tornar uma pessoa que outras pessoas lembram e querem ter por perto.",
            ],
            "ideias_chave": [
                "Momento único: criar uma experiência ou conversa que se destaca das interações comuns do dia a dia.",
                "Detalhes pessoais: lembrar e mencionar detalhes específicos que a outra pessoa compartilhou mostra que você presta atenção.",
                "Impacto emocional: criar momentos que tocam emocionalmente — riso genuíno, reflexão profunda, conexão autêntica.",
                "Autenticidade memorável: ser genuinamente você, não uma versão genérica. Sua singularidade é o que te torna memorável.",
                "Follow-up significativo: depois de uma interação, fazer um follow-up que mostra que você lembrou e valorizou o momento.",
            ],
            "aplicacao": [
                "Crie momentos únicos: \"Lembrei de você quando vi isso\" ou \"Isso me fez pensar na nossa conversa\" mostra que você pensa na pessoa.",
                "Lembre de detalhes: \"Você mencionou que gosta de X. Encontrei algo relacionado\" mostra atenção genuína.",
                "Crie impacto emocional: uma conversa que faz rir genuinamente, uma reflexão que toca, um momento de conexão autêntica.",
                "Seja autenticamente você: sua singularidade — seus interesses, sua perspectiva, seu jeito — é o que te torna memorável.",
                "Faça follow-up significativo: \"Nossa conversa de ontem me fez pensar...\" ou \"Lembrei de você quando...\" mostra impacto duradouro.",
                "Compartilhe algo único: uma história, uma perspectiva, uma experiência que a maioria das pessoas não compartilha.",
                "Crie associações positivas: quando a pessoa pensar em você, que emoção ela sente? Alegria? Calma? Inspiração?",
                "Seja consistente: ser memorável não é sobre uma grande performance, mas sobre ser consistentemente presente, autêntico e valoroso.",
            ],
            "exercicios": [
                "Pratique lembrar detalhes: em 2 conversas, mencione 1 detalhe específico que a pessoa compartilhou anteriormente.",
                "Crie 1 momento único: faça algo ou diga algo que crie uma experiência memorável em uma interação.",
                "Pratique follow-up: após uma conversa significativa, faça 1 follow-up que mostre que você lembrou e valorizou.",
                "Anote sua singularidade: liste 3 coisas que te tornam único e memorável (interesses, perspectiva, jeito).",
            ],
            "frases": [
                "\"Lembrei de você quando vi isso. Pensei que você gostaria.\"",
                "\"Nossa conversa de ontem me fez pensar sobre...\"",
                "\"Você mencionou que gosta de X. Encontrei algo relacionado.\"",
                "\"Essa conversa foi especial. Vou lembrar dela.\"",
                "\"Você tem um jeito único de ver as coisas. Isso é memorável.\"",
            ],
            "checklist": [
                "Criei um momento único que se destaca das interações comuns?",
                "Lembrei e mencionei detalhes específicos que a pessoa compartilhou?",
                "Criei impacto emocional positivo (riso, reflexão, conexão)?",
                "Fui autenticamente eu, não uma versão genérica?",
            ],
            "resumo": [
                "Ser memorável é sobre criar momentos únicos, lembrar detalhes pessoais e criar impacto emocional positivo. Sua autenticidade é sua maior força.",
                "Follow-up significativo mostra que você valorizou a interação e pensa na pessoa além do momento presente.",
                "Consistência é mais importante que performance. Seja consistentemente presente, autêntico e valoroso para se tornar memorável.",
            ],
        }
    
    # Capítulo 9: Reciprocidade e Consistência
    elif chapter_num == 9:
        return {
            "visao_geral": [
                "Reciprocidade é a base de qualquer conexão saudável. Quando há investimento mútuo — tempo, atenção, cuidado — a conexão se fortalece naturalmente.",
                "Este capítulo explora como desenvolver reciprocidade através de consistência, equilíbrio e investimento genuíno.",
            ],
            "ideias_chave": [
                "Investimento equilibrado: ambas as partes devem investir tempo, atenção e cuidado de forma relativamente equilibrada.",
                "Consistência: ser previsível no bom sentido — confiável, presente, autêntico — cria segurança emocional.",
                "Iniciativa mútua: não seja sempre você a iniciar. Se a outra pessoa nunca toma iniciativa, pode não haver interesse real.",
                "Resposta ao investimento: quando alguém investe em você, reconheça e retribua de forma apropriada.",
                "Sinais de desequilíbrio: se você sempre inicia, sempre investe mais, sempre se esforça mais, pode ser hora de ajustar expectativas.",
            ],
            "aplicacao": [
                "Observe investimento mútuo: quem inicia conversas? Quem faz perguntas? Quem investe tempo? Se for sempre você, há desequilíbrio.",
                "Seja consistente: responda mensagens, apareça quando diz que vai aparecer, seja presente de forma previsível e confiável.",
                "Tome iniciativa, mas observe resposta: inicie conversas e interações, mas observe se a outra pessoa também toma iniciativa.",
                "Reconheça investimento: \"Obrigado por pensar em mim\" ou \"Aprecio que você tenha feito isso\" mostra que você valoriza o investimento.",
                "Retribua de forma apropriada: se alguém investe tempo em você, retribua com tempo. Se investe atenção, retribua com atenção.",
                "Ajuste expectativas: se há desequilíbrio consistente, ajuste suas expectativas. Não invista mais do que recebe de volta.",
                "Comunique limites: \"Eu tenho investido bastante, mas preciso ver reciprocidade\" comunica limites de forma respeitosa.",
                "Pratique paciência: reciprocidade pode levar tempo para se desenvolver. Dê espaço, mas observe padrões ao longo do tempo.",
            ],
            "exercicios": [
                "Observe investimento: por 1 semana, anote quem inicia conversas e interações. Há equilíbrio?",
                "Pratique consistência: seja previsível e confiável em 3 interações. Observe como isso cria segurança.",
                "Reconheça investimento: em 2 interações, reconheça explicitamente quando a outra pessoa investe em você.",
                "Avalie desequilíbrio: se há desequilíbrio consistente, liste 3 ajustes que você pode fazer nas suas expectativas.",
            ],
            "frases": [
                "\"Obrigado por pensar em mim. Isso significa muito.\"",
                "\"Aprecio que você tenha investido tempo nisso. Vou retribuir.\"",
                "\"Eu tenho investido bastante, mas preciso ver reciprocidade.\"",
                "\"Você também toma iniciativa. Isso é importante para mim.\"",
                "\"Há equilíbrio entre nós. Isso é saudável.\"",
            ],
            "checklist": [
                "Observei investimento mútuo (quem inicia, quem investe tempo, quem toma iniciativa)?",
                "Fui consistente e previsível no bom sentido?",
                "Reconheci e retribuí investimento da outra pessoa?",
                "Ajustei expectativas se há desequilíbrio consistente?",
            ],
            "resumo": [
                "Reciprocidade requer investimento mútuo equilibrado. Observe quem inicia, quem investe tempo e quem toma iniciativa.",
                "Consistência cria segurança emocional. Seja previsível no bom sentido — confiável, presente, autêntico.",
                "Se há desequilíbrio consistente, ajuste expectativas. Não invista mais do que recebe de volta.",
            ],
        }
    
    # Capítulo 10: Limites e Ética (Contexto do Trabalho)
    elif chapter_num == 10:
        return {
            "visao_geral": [
                "No contexto profissional, limites e ética são ainda mais importantes. Respeitar limites, manter discrição e agir com maturidade são essenciais para conexões saudáveis no ambiente de trabalho.",
                "Este capítulo explora como desenvolver conexões respeitosas e éticas em contextos profissionais.",
            ],
            "ideias_chave": [
                "Discrição profissional: manter privacidade e não expor a outra pessoa a fofocas ou situações constrangedoras.",
                "Limites claros: entender e respeitar os limites do ambiente profissional — horários, espaços, comportamentos apropriados.",
                "Consentimento explícito: em contextos profissionais, consentimento deve ser ainda mais claro e explícito.",
                "Hierarquia e poder: estar ciente de dinâmicas de poder e hierarquia que podem afetar a dinâmica da conexão.",
                "Separação público/privado: manter separação entre interações profissionais e pessoais quando apropriado.",
            ],
            "aplicacao": [
                "Mantenha discrição: não compartilhe detalhes de interações pessoais com colegas. Respeite a privacidade da outra pessoa.",
                "Respeite limites profissionais: horários de trabalho, espaços apropriados, comportamentos que são aceitáveis no ambiente profissional.",
                "Seja explícito sobre intenções: \"Gostaria de convidar você para um café fora do trabalho. Você estaria interessado(a)?\"",
                "Esteja ciente de hierarquia: se há diferença de poder (chefe/colaborador), seja ainda mais cuidadoso e respeitoso.",
                "Mantenha separação: interações profissionais devem permanecer profissionais. Se houver interesse pessoal, comunique claramente.",
                "Evite pressão: no ambiente de trabalho, pressão pode ser ainda mais problemática. Respeite \"não\" imediatamente.",
                "Use canais apropriados: mensagens pessoais devem ser apropriadas. Evite mensagens que possam ser interpretadas como inapropriadas.",
                "Documente consentimento: em situações sensíveis, tenha clareza sobre consentimento e limites para evitar mal-entendidos.",
            ],
            "exercicios": [
                "Avalie limites profissionais: liste 3 limites que você deve respeitar no seu ambiente de trabalho.",
                "Pratique discrição: em 1 semana, não compartilhe detalhes pessoais de interações com colegas.",
                "Pratique consentimento explícito: faça 1 convite explícito e respeite a resposta, seja qual for.",
                "Avalie dinâmica de poder: se há hierarquia, liste 3 cuidados adicionais que você deve ter.",
            ],
            "frases": [
                "\"Gostaria de convidar você para um café fora do trabalho. Você estaria interessado(a)?\"",
                "\"Respeito completamente se você preferir manter nossa relação profissional.\"",
                "\"Entendo os limites do ambiente de trabalho. Vou respeitar isso.\"",
                "\"Se você mudar de ideia, me avise. Sem pressão.\"",
                "\"Valorizo nossa conexão, mas respeito os limites profissionais.\"",
            ],
            "checklist": [
                "Mantive discrição e não expus a outra pessoa a situações constrangedoras?",
                "Respeitei limites profissionais (horários, espaços, comportamentos)?",
                "Fui explícito sobre intenções e respeitei a resposta?",
                "Estive ciente de dinâmicas de poder e hierarquia?",
            ],
            "resumo": [
                "No contexto profissional, limites e ética são ainda mais importantes. Mantenha discrição, respeite limites e seja explícito sobre intenções.",
                "Esteja ciente de dinâmicas de poder e hierarquia. Seja ainda mais cuidadoso e respeitoso quando há diferença de poder.",
                "Consentimento deve ser explícito e claro. Respeite \"não\" imediatamente, especialmente no ambiente de trabalho.",
            ],
        }
    
    # Capítulo 11: Criando Interesse Sem Forçar
    elif chapter_num == 11:
        return {
            "visao_geral": [
                "Interesse genuíno não pode ser forçado. Mas você pode criar condições que tornam o interesse mais provável através de valor, presença e autenticidade.",
                "Este capítulo ensina como criar interesse de forma natural, sem parecer desesperado ou forçado.",
            ],
            "ideias_chave": [
                "Valor percebido: quando você tem valor — habilidades, caráter, presença — você naturalmente se torna interessante.",
                "Mistério positivo: não revelar tudo de uma vez cria curiosidade e interesse. Mas não seja evasivo demais.",
                "Vida própria: ter uma vida rica e interessante fora da conexão mostra que você não depende dela para ser feliz.",
                "Presença magnética: quando você está presente, autêntico e confiante, você naturalmente atrai atenção.",
                "Sem necessidade: quando você não precisa da conexão para ser feliz, você se torna mais atraente.",
            ],
            "aplicacao": [
                "Desenvolva valor: invista em você — habilidades, interesses, crescimento pessoal. Pessoas valiosas são naturalmente interessantes.",
                "Mantenha mistério positivo: não compartilhe tudo de uma vez. Deixe espaço para curiosidade e descoberta gradual.",
                "Tenha vida própria: mantenha seus interesses, hobbies, amigos, rotina. Não abandone sua vida pela conexão.",
                "Pratique presença magnética: esteja totalmente presente, autêntico e confiante. Isso naturalmente atrai atenção.",
                "Elimine necessidade: quando você não precisa da conexão, você se torna mais atraente. Trabalhe em ser feliz sozinho.",
                "Seja seletivo: não esteja disponível o tempo todo. Ter limites e ser seletivo mostra valor.",
                "Crie valor na interação: traga algo positivo — riso, reflexão, conexão, crescimento. Seja alguém que adiciona valor.",
                "Não force: se o interesse não existe, não force. Foque em ser a melhor versão de você e deixe o interesse surgir naturalmente.",
            ],
            "exercicios": [
                "Desenvolva valor: liste 3 áreas onde você pode investir em crescimento pessoal (habilidades, interesses, caráter).",
                "Pratique mistério positivo: em 2 conversas, não revele tudo de uma vez. Deixe espaço para curiosidade.",
                "Mantenha vida própria: esta semana, mantenha 3 atividades que você faz independentemente da conexão.",
                "Avalie necessidade: você precisa dessa conexão para ser feliz? Se sim, trabalhe em ser feliz sozinho primeiro.",
            ],
            "frases": [
                "\"Tenho uma vida interessante. Gosto de manter um equilíbrio.\"",
                "\"Não compartilho tudo de uma vez. Prefiro que as pessoas me descubram gradualmente.\"",
                "\"Valorizo minha independência. Isso me torna uma pessoa melhor.\"",
                "\"Não preciso dessa conexão para ser feliz. Mas gosto dela.\"",
                "\"Tenho limites. Isso mostra que eu me valorizo.\"",
            ],
            "checklist": [
                "Desenvolvi valor pessoal (habilidades, interesses, crescimento)?",
                "Mantive mistério positivo sem ser evasivo demais?",
                "Mantive vida própria independente da conexão?",
                "Eliminei necessidade excessiva da conexão?",
            ],
            "resumo": [
                "Interesse genuíno não pode ser forçado. Desenvolva valor, mantenha mistério positivo e tenha vida própria para criar condições que tornam o interesse mais provável.",
                "Presença magnética — estar presente, autêntico e confiante — naturalmente atrai atenção. Trabalhe em ser a melhor versão de você.",
                "Quando você não precisa da conexão para ser feliz, você se torna mais atraente. Elimine necessidade excessiva e foque em ser feliz sozinho primeiro.",
            ],
        }
    
    # Capítulo 12: Confiança Silenciosa
    elif chapter_num == 12:
        return {
            "visao_geral": [
                "Confiança silenciosa não precisa ser anunciada. É uma presença calma, segura e autêntica que comunica valor sem palavras.",
                "Este capítulo explora como desenvolver confiança silenciosa através de postura, presença e autenticidade.",
            ],
            "ideias_chave": [
                "Postura confiante: corpo ereto mas relaxado, movimentos calmos, gestos abertos. Confiança se comunica através do corpo.",
                "Voz calma: ritmo mais lento, pausas naturais, tom estável. Voz calma comunica segurança e controle emocional.",
                "Presença sem ansiedade: estar presente sem necessidade de impressionar ou validar. Confiança não precisa de aprovação externa.",
                "Autenticidade: ser genuinamente você, sem tentar ser alguém que você não é. Autenticidade é a base da confiança real.",
                "Silêncio confortável: estar confortável com silêncios. Não preencher todos os espaços com palavras mostra confiança.",
            ],
            "aplicacao": [
                "Pratique postura confiante: corpo ereto mas relaxado, ombros abertos, movimentos calmos. Confiança se comunica através do corpo.",
                "Desenvolva voz calma: fale 20% mais devagar, faça pausas naturais, mantenha tom estável. Voz calma comunica segurança.",
                "Elimine necessidade de aprovação: você não precisa impressionar ou validar. Seja você mesmo e confie no seu valor.",
                "Pratique autenticidade: seja genuinamente você, não uma versão que você acha que outras pessoas querem ver.",
                "Esteja confortável com silêncios: não preencha todos os espaços com palavras. Silêncios confortáveis mostram confiança.",
                "Mantenha contato visual confortável: olhe nos olhos com calma, sem fixar intensamente. Contato visual confortável comunica confiança.",
                "Use gestos abertos: braços relaxados, palmas ocasionalmente visíveis. Gestos abertos comunicam abertura e confiança.",
                "Respire profundamente: respiração profunda acalma o sistema nervoso e comunica confiança através da calma física.",
            ],
            "exercicios": [
                "Pratique postura confiante: em 3 interações, mantenha corpo ereto mas relaxado e observe como isso muda a dinâmica.",
                "Pratique voz calma: fale 20% mais devagar em 2 conversas e observe o impacto.",
                "Pratique silêncios: em 1 conversa, faça 3 pausas de 3 segundos e observe como isso mostra confiança.",
                "Avalie necessidade de aprovação: você precisa impressionar? Se sim, trabalhe em eliminar essa necessidade.",
            ],
            "frases": [
                "\"Não tenho pressa. Podemos conversar com calma.\"",
                "\"Estou confortável com silêncios. Eles dão espaço para pensar.\"",
                "\"Não preciso impressionar. Sou quem sou.\"",
                "\"Confio no meu valor. Não preciso validar isso.\"",
                "\"Estou presente. Isso é suficiente.\"",
            ],
            "checklist": [
                "Mantive postura confiante (corpo ereto mas relaxado)?",
                "Falei com voz calma (ritmo mais lento, pausas naturais)?",
                "Eliminei necessidade de aprovação ou validação?",
                "Estive confortável com silêncios?",
            ],
            "resumo": [
                "Confiança silenciosa comunica valor sem palavras. Pratique postura confiante, voz calma e presença sem ansiedade.",
                "Autenticidade é a base da confiança real. Seja genuinamente você, não uma versão que você acha que outras pessoas querem ver.",
                "Silêncios confortáveis mostram confiança. Não preencha todos os espaços com palavras. Esteja presente e confie no seu valor.",
            ],
        }
    
    # Capítulo 13: Admiração no Longo Prazo
    elif chapter_num == 13:
        return {
            "visao_geral": [
                "Admiração no longo prazo não vem de aparência ou performance inicial. Vem de caráter, consistência, crescimento e valores que se manifestam ao longo do tempo.",
                "Este capítulo explora como desenvolver admiração duradoura através de ações consistentes e valores sólidos.",
            ],
            "ideias_chave": [
                "Caráter: integridade, honestidade, responsabilidade. Caráter se mostra através de ações, não palavras.",
                "Consistência: ser previsível no bom sentido — confiável, presente, autêntico — ao longo do tempo.",
                "Crescimento: mostrar evolução pessoal, aprendizado contínuo, abertura para feedback e mudança.",
                "Valores em ação: valores não são o que você diz, mas o que você faz. Mostre valores através de ações consistentes.",
                "Impacto positivo: ser alguém que adiciona valor à vida da outra pessoa — apoio, crescimento, alegria, conexão.",
            ],
            "aplicacao": [
                "Demonstre caráter: seja honesto, responsável, íntegro. Caráter se mostra através de ações consistentes ao longo do tempo.",
                "Mantenha consistência: seja confiável, presente, autêntico. Consistência cria segurança e admiração no longo prazo.",
                "Mostre crescimento: esteja aberto a aprender, evoluir, mudar. Crescimento contínuo é admirável.",
                "Viva seus valores: não apenas fale sobre valores, mas mostre-os através de ações. Valores em ação são admiráveis.",
                "Adicione valor: seja alguém que adiciona valor à vida da outra pessoa — apoio emocional, crescimento, alegria, conexão.",
                "Seja confiável: apareça quando diz que vai aparecer, cumpra compromissos, seja presente de forma consistente.",
                "Pratique responsabilidade: assuma responsabilidade por suas ações, erros e crescimento. Responsabilidade é admirável.",
                "Mantenha integridade: seja honesto mesmo quando é difícil. Integridade cria admiração e confiança no longo prazo.",
            ],
            "exercicios": [
                "Demonstre caráter: esta semana, faça 3 ações que demonstrem integridade, honestidade ou responsabilidade.",
                "Mantenha consistência: por 1 semana, seja previsível e confiável em todas as interações.",
                "Mostre crescimento: peça feedback e esteja aberto a aprender e evoluir em 1 área da sua vida.",
                "Avalie valores em ação: seus valores se manifestam através de ações? Liste 3 ações que demonstram seus valores.",
            ],
            "frases": [
                "\"Assumo responsabilidade por isso. Vou trabalhar para melhorar.\"",
                "\"Valorizo integridade. Isso é importante para mim.\"",
                "\"Estou sempre aberto a aprender e crescer.\"",
                "\"Quero adicionar valor à sua vida, não apenas receber.\"",
                "\"Consistência é importante para mim. Você pode contar comigo.\"",
            ],
            "checklist": [
                "Demonstrei caráter através de ações consistentes?",
                "Mantive consistência (confiável, presente, autêntico)?",
                "Mostrei crescimento e abertura para aprender?",
                "Vivi meus valores através de ações, não apenas palavras?",
            ],
            "resumo": [
                "Admiração no longo prazo vem de caráter, consistência, crescimento e valores que se manifestam através de ações ao longo do tempo.",
                "Valores não são o que você diz, mas o que você faz. Mostre valores através de ações consistentes para criar admiração duradoura.",
                "Seja alguém que adiciona valor à vida da outra pessoa. Impacto positivo cria admiração e conexão no longo prazo.",
            ],
        }
    
    # Capítulo 14: Erros que Rompem Conexão
    elif chapter_num == 14:
        return {
            "visao_geral": [
                "Alguns erros podem romper conexões que estavam se desenvolvendo bem. Reconhecer e evitar esses erros é essencial para manter conexões saudáveis.",
                "Este capítulo identifica erros comuns que rompem conexão e como evitá-los.",
            ],
            "ideias_chave": [
                "Necessidade excessiva: demonstrar necessidade excessiva, dependência emocional ou desespero afasta as pessoas.",
                "Pressão e insistência: pressionar, insistir ou não respeitar \"não\" rompe confiança e conexão imediatamente.",
                "Inautenticidade: tentar ser alguém que você não é, criar uma persona falsa ou manipular destrói confiança.",
                "Falta de respeito: não respeitar limites, tempo, espaço ou consentimento da outra pessoa rompe conexão.",
                "Jogos e manipulação: usar técnicas manipulativas, jogos psicológicos ou estratégias desonestas destrói confiança.",
            ],
            "aplicacao": [
                "Elimine necessidade excessiva: trabalhe em ser feliz sozinho. Necessidade excessiva afasta as pessoas.",
                "Respeite \"não\": quando alguém diz \"não\", respeite imediatamente. Pressão e insistência rompem conexão.",
                "Seja autêntico: seja você mesmo, não uma versão que você acha que outras pessoas querem ver. Inautenticidade destrói confiança.",
                "Respeite limites: sempre respeite limites, tempo, espaço e consentimento. Falta de respeito rompe conexão imediatamente.",
                "Evite jogos: não use técnicas manipulativas ou jogos psicológicos. Seja direto, honesto e autêntico.",
                "Não force: se a conexão não está acontecendo, não force. Forçar rompe conexão e destrói qualquer possibilidade futura.",
                "Comunique-se claramente: evite jogos, indiretas ou manipulação. Clareza e honestidade mantêm conexão.",
                "Mantenha seus valores: não abandone seus valores para agradar outra pessoa. Isso cria inautenticidade e rompe conexão.",
            ],
            "exercicios": [
                "Avalie necessidade: você demonstra necessidade excessiva? Se sim, trabalhe em ser feliz sozinho.",
                "Pratique respeito: esta semana, respeite imediatamente todos os \"não\" que receber, sem questionar ou insistir.",
                "Avalie autenticidade: você está sendo genuinamente você, ou tentando ser alguém que você não é?",
                "Liste erros: identifique 3 erros que você cometeu no passado que podem ter rompido conexões.",
            ],
            "frases": [
                "\"Respeito completamente sua decisão. Sem pressão.\"",
                "\"Não quero forçar nada. Se não há abertura, está tudo bem.\"",
                "\"Prefiro ser honesto e direto, não jogar jogos.\"",
                "\"Respeito seus limites. Isso é importante para mim.\"",
                "\"Não preciso dessa conexão para ser feliz. Mas gosto dela.\"",
            ],
            "checklist": [
                "Eliminei necessidade excessiva e dependência emocional?",
                "Respeitei \"não\" imediatamente, sem pressão ou insistência?",
                "Fui autêntico, não tentando ser alguém que não sou?",
                "Respeitei limites, tempo, espaço e consentimento?",
            ],
            "resumo": [
                "Erros comuns que rompem conexão incluem necessidade excessiva, pressão, inautenticidade, falta de respeito e jogos manipulativos.",
                "Respeite \"não\" imediatamente. Pressão e insistência rompem conexão e destroem qualquer possibilidade futura.",
                "Seja autêntico e honesto. Inautenticidade, jogos e manipulação destroem confiança e rompem conexão permanentemente.",
            ],
        }
    
    # Capítulo 15: Diálogos Práticos
    elif chapter_num == 15:
        return {
            "visao_geral": [
                "Diálogos práticos são exemplos reais de como aplicar os princípios deste livro em situações do dia a dia.",
                "Este capítulo apresenta diálogos práticos que ilustram comunicação madura, respeito e conexão autêntica.",
            ],
            "ideias_chave": [
                "Diálogos reais: exemplos práticos de conversas que demonstram os princípios do livro em ação.",
                "Situações variadas: diferentes contextos — trabalho, social, inicial, aprofundamento — para mostrar aplicação prática.",
                "Tom e linguagem: exemplos de tom, linguagem e abordagem que funcionam em diferentes situações.",
                "Respostas apropriadas: como responder a diferentes situações de forma respeitosa, autêntica e eficaz.",
                "Adaptação: como adaptar os princípios para diferentes personalidades, contextos e situações.",
            ],
            "aplicacao": [
                "Use diálogos como referência: adapte os exemplos para sua situação, personalidade e contexto específico.",
                "Observe tom e linguagem: preste atenção ao tom, linguagem e abordagem usados nos diálogos práticos.",
                "Pratique variações: experimente diferentes formas de dizer a mesma coisa para encontrar seu estilo autêntico.",
                "Adapte para seu contexto: ajuste os diálogos para seu ambiente, relação e situação específica.",
                "Pratique gradualmente: comece com situações mais simples e gradualmente aplique em situações mais complexas.",
                "Seja autêntico: use os diálogos como inspiração, mas encontre sua própria voz e estilo autêntico.",
                "Observe respostas: preste atenção às respostas e ajuste sua abordagem baseado no feedback que recebe.",
                "Mantenha princípios: mesmo adaptando, mantenha os princípios fundamentais — respeito, autenticidade, clareza.",
            ],
            "exercicios": [
                "Pratique diálogos: escolha 2 diálogos práticos e adapte para sua situação específica.",
                "Observe tom: em 2 conversas, preste atenção ao tom e linguagem que você usa e ajuste se necessário.",
                "Pratique variações: experimente 3 formas diferentes de dizer a mesma coisa e encontre seu estilo.",
                "Avalie adaptação: você está adaptando os princípios para seu contexto sem perder autenticidade?",
            ],
            "frases": [
                "\"Gostaria de conversar com você. Você tem um tempinho?\"",
                "\"Curti nossa conversa. Gostaria de continuar em outro momento?\"",
                "\"Respeito completamente se você preferir não. Sem pressão.\"",
                "\"Essa conversa foi especial. Obrigado por compartilhar isso comigo.\"",
                "\"Valorizo nossa conexão. Espero que possamos continuar conversando.\"",
            ],
            "checklist": [
                "Usei diálogos práticos como referência e adaptei para minha situação?",
                "Observei tom e linguagem e ajustei para ser mais autêntico?",
                "Pratiquei variações e encontrei meu estilo pessoal?",
                "Mantive princípios fundamentais (respeito, autenticidade, clareza)?",
            ],
            "resumo": [
                "Diálogos práticos são exemplos reais de como aplicar os princípios do livro. Use-os como referência e adapte para sua situação.",
                "Encontre seu estilo autêntico. Use os diálogos como inspiração, mas desenvolva sua própria voz e abordagem.",
                "Mantenha os princípios fundamentais — respeito, autenticidade, clareza — mesmo ao adaptar para diferentes contextos.",
            ],
        }
    
    # Capítulo 16: O Código Final
    elif chapter_num == 16:
        return {
            "visao_geral": [
                "O código final não é uma fórmula mágica, mas uma síntese dos princípios fundamentais que criam conexão autêntica e duradoura.",
                "Este capítulo integra todos os conceitos do livro em um código prático e aplicável.",
            ],
            "ideias_chave": [
                "Síntese: integração de todos os princípios — presença, autenticidade, respeito, reciprocidade — em um código unificado.",
                "Aplicação prática: como aplicar o código no dia a dia de forma consistente e natural.",
                "Evolução contínua: o código não é estático, mas evolui conforme você cresce e aprende.",
                "Personalização: adapte o código para sua personalidade, valores e contexto específico.",
                "Consistência: aplicar o código consistentemente ao longo do tempo cria conexões duradouras.",
            ],
            "aplicacao": [
                "Integre os princípios: combine presença, autenticidade, respeito e reciprocidade em uma abordagem unificada.",
                "Aplique consistentemente: use o código no dia a dia de forma consistente, não apenas ocasionalmente.",
                "Evolua continuamente: esteja aberto a aprender, ajustar e evoluir o código conforme você cresce.",
                "Personalize: adapte o código para sua personalidade, valores e contexto, mantendo os princípios fundamentais.",
                "Pratique regularmente: como qualquer habilidade, o código requer prática regular para se tornar natural.",
                "Observe resultados: preste atenção aos resultados e ajuste sua aplicação baseado no que funciona para você.",
                "Mantenha simplicidade: o código não precisa ser complicado. Princípios simples aplicados consistentemente são poderosos.",
                "Seja paciente: conexões profundas levam tempo. Aplique o código com paciência e consistência.",
            ],
            "exercicios": [
                "Crie seu código: integre os princípios do livro em um código pessoal de 5 pontos que você pode aplicar consistentemente.",
                "Pratique aplicação: esta semana, aplique seu código em 3 interações e observe os resultados.",
                "Avalie evolução: como seu código evoluiu desde o início do livro? Liste 3 ajustes que você fez.",
                "Personalize: adapte o código para sua personalidade e contexto, mantendo os princípios fundamentais.",
            ],
            "frases": [
                "\"Aplico esses princípios consistentemente. Eles guiam minhas interações.\"",
                "\"Meu código evolui conforme eu cresço. Estou sempre aprendendo.\"",
                "\"Adapto os princípios para minha personalidade, mas mantenho os fundamentos.\"",
                "\"Consistência é a chave. Aplico o código regularmente, não apenas ocasionalmente.\"",
                "\"O código não é complicado. Princípios simples aplicados consistentemente são poderosos.\"",
            ],
            "checklist": [
                "Integrei os princípios em um código unificado que posso aplicar consistentemente?",
                "Apliquei o código regularmente, não apenas ocasionalmente?",
                "Evoluí e ajustei o código conforme aprendi e cresci?",
                "Personalizei o código para minha personalidade mantendo os princípios fundamentais?",
            ],
            "resumo": [
                "O código final é uma síntese dos princípios fundamentais — presença, autenticidade, respeito, reciprocidade — aplicados consistentemente.",
                "Personalize o código para sua personalidade e contexto, mas mantenha os princípios fundamentais. Simplicidade e consistência são poderosas.",
                "Evolua continuamente. O código não é estático, mas cresce e se adapta conforme você aprende e desenvolve suas habilidades.",
            ],
        }
    
    # Fallback (não deve acontecer)
    else:
        # Conteúdo genérico de fallback
        return {
            "visao_geral": [
                f"{chapter_title} é um aspecto importante da conexão humana.",
                "Este capítulo explora os princípios e práticas que permitem desenvolver essa habilidade.",
            ],
            "ideias_chave": [
                "Autenticidade: seja você mesmo.",
                "Respeito: sempre respeite os limites.",
                "Paciência: conexões levam tempo.",
                "Clareza: comunique-se com clareza.",
                "Reciprocidade: observe investimento mútuo.",
            ],
            "aplicacao": [
                "Pratique autenticidade.",
                "Respeite limites.",
                "Tenha paciência.",
                "Comunique-se claramente.",
                "Observe reciprocidade.",
            ],
            "exercicios": [
                "Pratique autenticidade.",
                "Observe reciprocidade.",
                "Pratique clareza.",
                "Reflita sobre valores.",
            ],
            "frases": [
                "\"Curti conversar com você hoje.\"",
                "\"Você tem um jeito interessante de ver as coisas.\"",
                "\"Fala mais — eu quero entender teu ponto.\"",
                "\"Sem pressa… a gente resolve isso com calma.\"",
                "\"Se você topar, qualquer dia a gente toma um café.\"",
            ],
            "checklist": [
                "Fui autêntico(a)?",
                "Respeitei limites?",
                "Comuniquei-me com clareza?",
                "Observei reciprocidade?",
            ],
            "resumo": [
                f"{chapter_title} se desenvolve através de autenticidade, respeito e clareza.",
                "Mantenha seus valores e rotina.",
                "Pratique presença e observe reciprocidade.",
            ],
        }


# =========================
# GERADOR DE PÁGINAS
# =========================
def create_page(content: str, is_last: bool = False) -> str:
    """Cria uma página HTML com quebra de página."""
    break_after = "" if is_last else ' page-break-after: always;'
    return f'<div class="page" style="{break_after}">{content}</div>'


def create_chapter_pages(chapter_num: int, chapter_title: str, num_pages: int) -> str:
    """Cria as páginas de um capítulo."""
    chap_id = f"cap-{chapter_num:02d}"
    
    # Seleciona conteúdo baseado no número do capítulo
    if chapter_num == 1:
        content = CHAPTER_1_CONTENT
    elif chapter_num == 2:
        content = CHAPTER_2_CONTENT
    elif chapter_num == 3:
        content = CHAPTER_3_CONTENT
    else:
        content = get_chapter_content(chapter_num, chapter_title)
    
    pages_html = []
    
    # Página 1: Título + Visão geral + Ideias-chave
    page1 = f"""
  <h1>{escape_html(f"Capítulo {chapter_num} — {chapter_title}")}</h1>
  <div class="chapter-meta">Data: {TODAY} • {escape_html(BOOK_TITLE)}</div>
  {h2_tag("Visão geral")}
  {"".join(p_tag(p) for p in content["visao_geral"])}
  {h2_tag("Ideias-chave")}
  {ul_tag(content["ideias_chave"])}
"""
    pages_html.append(create_page(page1))
    
    # Página 2: Aplicação prática (primeira parte)
    page2 = f"""
  {h2_tag("Aplicação prática")}
  {"".join(p_tag(p) for p in content["aplicacao"][:4])}
"""
    pages_html.append(create_page(page2))
    
    # Página 3: Aplicação prática (continuação) + Exercícios
    page3 = f"""
  {h2_tag("Aplicação prática (continuação)")}
  {"".join(p_tag(p) for p in content["aplicacao"][4:])}
  {h2_tag("Exercícios")}
  {ul_tag(content["exercicios"])}
"""
    pages_html.append(create_page(page3))
    
    # Página 4: Frases úteis + Checklist + Notas
    page4 = f"""
  {h2_tag("Frases úteis (naturais, sem manipulação)")}
  {ul_tag(content["frases"])}
  {h2_tag("Checklist do capítulo")}
  {ul_tag(content["checklist"])}
  {h2_tag("Notas e reflexão")}
  {"".join(p_tag(p) for p in content["aplicacao"][:2])}
"""
    pages_html.append(create_page(page4))
    
    # Página 5: Apenas para capítulos 1-13
    if num_pages >= 5:
        page5 = f"""
  {h2_tag("Resumo e prática da semana")}
  {"".join(p_tag(p) for p in content["resumo"])}
  {h2_tag("Guia rápido")}
  <p>Revise este capítulo ao longo da semana. Pratique os exercícios diariamente e observe os resultados. A consistência é mais importante que a perfeição.</p>
  <p>Mantenha um diário simples: anote uma interação por dia e avalie usando o checklist. Isso desenvolve autoconsciência e melhora contínua.</p>
  <p>Lembre-se: o objetivo não é impressionar, mas conectar de forma autêntica e respeitosa. Quando você pratica presença e respeito, a conexão acontece naturalmente.</p>
"""
        pages_html.append(create_page(page5))
    
    # Envolve tudo em uma seção de capítulo
    return f'<section class="chapter" id="{chap_id}">{"".join(pages_html)}</section>'


# =========================
# HTML + CSS COMPLETO
# =========================
def build_html() -> str:
    """Constrói o HTML completo do livro."""
    
    # Sumário
    toc_items = []
    toc_items.append(f'<li><a href="#intro">Introdução — Como usar este livro</a></li>')
    for i, title in enumerate(CHAPTERS, start=1):
        toc_items.append(f'<li><a href="#cap-{i:02d}">Capítulo {i} — {escape_html(title)}</a></li>')
    toc_items.append(f'<li><a href="#conclusao">Notas do Leitor</a></li>')
    
    # Capítulos
    chapters_html = []
    for i, (title, num_pages) in enumerate(zip(CHAPTERS, CHAPTER_PAGE_BUDGET), start=1):
        is_last_chapter = (i == len(CHAPTERS))
        chapter_html = create_chapter_pages(i, title, num_pages)
        chapters_html.append(chapter_html)
    
    # CSS elegante e completo (compatível com xhtml2pdf e WeasyPrint)
    css = """
@page {
  size: A4;
  margin: 2.5cm 2.2cm 2.5cm 2.2cm;
}

/* Nota: xhtml2pdf não suporta @top-left, @top-right, @bottom-center
   Esses recursos funcionam apenas com WeasyPrint */

/* ============================================
   RESET E BASE
   ============================================ */
html, body {
  font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif;
  color: #2c2c2c;
  line-height: 1.6;
  margin: 0;
  padding: 0;
  background-color: #ffffff;
}

/* ============================================
   TIPOGRAFIA
   ============================================ */
p {
  margin: 0 0 14px 0;
  font-size: 11.5pt;
  text-align: justify;
  text-indent: 0;
  orphans: 3;
  widows: 3;
}

h1 {
  font-family: "DejaVu Serif", "Georgia", "Times New Roman", serif;
  font-weight: 700;
  font-size: 24pt;
  margin: 0 0 16px 0;
  padding: 0;
  color: #1a1a1a;
  letter-spacing: -0.5px;
  line-height: 1.2;
  border-bottom: 3px solid #d4af37;
  padding-bottom: 8px;
  margin-bottom: 20px;
}

h2 {
  font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif;
  font-weight: 600;
  font-size: 13.5pt;
  margin: 24px 0 12px 0;
  padding: 0;
  color: #2c3e50;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  font-size: 12pt;
  border-left: 4px solid #d4af37;
  padding-left: 12px;
}

h3 {
  font-family: "DejaVu Sans", "Helvetica Neue", Arial, sans-serif;
  font-weight: 600;
  font-size: 11.5pt;
  margin: 18px 0 10px 0;
  color: #34495e;
}

/* ============================================
   LINKS
   ============================================ */
a {
  color: #2c3e50;
  text-decoration: none;
  border-bottom: 1px dotted #7f8c8d;
  transition: color 0.2s;
}

a:hover {
  color: #d4af37;
  border-bottom-color: #d4af37;
}

/* Numeração de páginas no sumário (funciona apenas com WeasyPrint) */
/* a::after {
  content: leader('.') ' ' target-counter(attr(href), page);
} */

/* ============================================
   LISTAS
   ============================================ */
ul, ol {
  margin: 0 0 16px 0;
  padding-left: 24px;
}

ul {
  list-style-type: none;
  padding-left: 0;
}

ul li {
  margin: 0 0 10px 0;
  font-size: 11.5pt;
  text-align: justify;
  padding-left: 24px;
  position: relative;
  line-height: 1.6;
}

ul li::before {
  content: "▸";
  position: absolute;
  left: 0;
  color: #d4af37;
  font-weight: bold;
  font-size: 12pt;
}

ul.checklist li::before {
  content: "✓";
  color: #27ae60;
}

ol {
  counter-reset: item;
  padding-left: 24px;
}

ol li {
  margin: 0 0 10px 0;
  font-size: 11.5pt;
  text-align: justify;
  padding-left: 8px;
  line-height: 1.6;
  display: block;
  counter-increment: item;
}

ol li::before {
  content: counter(item) ".";
  font-weight: 600;
  color: #2c3e50;
  margin-right: 8px;
}

li {
  margin: 0 0 8px 0;
  font-size: 11.5pt;
  text-align: justify;
}

/* ============================================
   CAPÍTULOS E PÁGINAS
   ============================================ */
.chapter {
  page-break-before: always;
  margin: 0;
  padding: 0;
}

.chapter-meta {
  font-size: 9pt;
  color: #7f8c8d;
  margin-bottom: 16px;
  font-style: italic;
  padding: 8px 0;
  border-top: 1px solid #ecf0f1;
  border-bottom: 1px solid #ecf0f1;
}

.page {
  min-height: 100%;
  padding: 0;
  margin: 0;
}

/* Divisor elegante entre seções */
hr.sep {
  border: none;
  border-top: 2px solid #ecf0f1;
  margin: 24px 0;
  width: 60%;
  margin-left: auto;
  margin-right: auto;
}

/* ============================================
   CAPA ELEGANTE
   ============================================ */
.cover {
  page-break-after: always;
  text-align: center;
  padding-top: 6cm;
  min-height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: linear-gradient(to bottom, #ffffff 0%, #f8f9fa 100%);
}

.cover .title {
  font-family: "DejaVu Serif", "Georgia", "Times New Roman", serif;
  font-weight: 700;
  font-size: 38pt;
  letter-spacing: 1px;
  margin-bottom: 16px;
  color: #1a1a1a;
  text-shadow: 1px 1px 2px rgba(0,0,0,0.05);
  line-height: 1.1;
}

.cover .subtitle {
  font-size: 15pt;
  color: #5a5a5a;
  margin-bottom: 42px;
  font-weight: 300;
  letter-spacing: 0.5px;
  font-style: italic;
}

.cover .gold-line {
  width: 50%;
  margin: 0 auto 42px auto;
  border-top: 3px solid #d4af37;
  box-shadow: 0 2px 4px rgba(212, 175, 55, 0.2);
}

.cover .meta {
  font-size: 12.5pt;
  margin: 6px 0;
  color: #4a4a4a;
  font-weight: 400;
}

.cover .meta b {
  color: #2c3e50;
  font-weight: 600;
}

/* ============================================
   SUMÁRIO ELEGANTE
   ============================================ */
.toc {
  page-break-after: always;
  padding: 0;
}

.toc h1 {
  margin-bottom: 12px;
  border-bottom: 3px solid #d4af37;
  padding-bottom: 10px;
  text-align: center;
  font-size: 22pt;
}

.toc .note {
  color: #7f8c8d;
  font-size: 10pt;
  margin-bottom: 20px;
  font-style: italic;
  text-align: center;
  padding: 8px;
  background-color: #f8f9fa;
  border-left: 3px solid #d4af37;
}

.toc ol {
  margin-left: 0;
  padding-left: 0;
  list-style: none;
  counter-reset: toc-counter;
}

.toc ol li {
  margin: 12px 0;
  padding: 10px 0 10px 40px;
  position: relative;
  border-bottom: 1px dotted #e0e0e0;
  transition: background-color 0.2s;
  counter-increment: toc-counter;
}

.toc ol li::before {
  content: counter(toc-counter);
  position: absolute;
  left: 0;
  top: 10px;
  font-weight: 600;
  color: #d4af37;
  font-size: 12pt;
  width: 30px;
  text-align: right;
  padding-right: 10px;
}

.toc ol li:hover {
  background-color: #f8f9fa;
  padding-left: 42px;
}

.toc ol li a {
  color: #2c3e50;
  font-size: 11.5pt;
  display: block;
}

.toc ol li a:hover {
  color: #d4af37;
  border-bottom: none;
}

/* ============================================
   DESTAQUES E BLOCOS
   ============================================ */
blockquote {
  margin: 20px 0;
  padding: 16px 20px;
  border-left: 4px solid #d4af37;
  background-color: #f8f9fa;
  font-style: italic;
  color: #4a4a4a;
  font-size: 11pt;
}

/* Caixas de destaque */
.highlight-box {
  background-color: #fff9e6;
  border: 1px solid #d4af37;
  border-left: 4px solid #d4af37;
  padding: 14px 18px;
  margin: 18px 0;
  border-radius: 2px;
}

/* ============================================
   MELHORIAS GERAIS
   ============================================ */
strong, b {
  font-weight: 600;
  color: #2c3e50;
}

em, i {
  font-style: italic;
  color: #4a4a4a;
}

/* Espaçamento entre parágrafos em seções */
section p + p {
  margin-top: 12px;
}

/* Primeira letra maior (opcional, pode não funcionar em todos os conversores) */
p:first-of-type::first-letter {
  font-size: 1.5em;
  font-weight: 600;
  color: #d4af37;
  float: left;
  line-height: 1;
  margin-right: 4px;
  margin-top: 2px;
}

/* ============================================
   RESPONSIVIDADE E QUEBRAS
   ============================================ */
.pagebreak {
  page-break-before: always;
}

.no-break {
  page-break-inside: avoid;
}

.keep-together {
  page-break-inside: avoid;
}

/* ============================================
   INTRODUÇÃO
   ============================================ */
#intro {
  background-color: #f8f9fa;
  padding: 20px;
  border: 1px solid #e0e0e0;
  border-left: 4px solid #d4af37;
}

#intro h1 {
  border-bottom: 3px solid #d4af37;
}

#intro p:first-of-type {
  font-size: 12pt;
  font-weight: 500;
  color: #2c3e50;
}
"""
    
    # HTML completo
    html = f"""<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8"/>
  <title>{escape_html(BOOK_TITLE)}</title>
  <style>{css}</style>
</head>
<body>

<section class="cover">
  <div class="title">{escape_html(BOOK_TITLE)}</div>
  <div class="subtitle">{escape_html(BOOK_SUBTITLE)}</div>
  <div class="gold-line"></div>
  <div class="meta"><b>Autor:</b> {escape_html(AUTHOR)}</div>
  <div class="meta"><b>Data:</b> {TODAY}</div>
</section>

<section class="toc">
  <h1>Sumário</h1>
  <div class="note">Clique em um capítulo para navegar no PDF (sumário com links e numeração automática).</div>
  <ol>
    {''.join(toc_items)}
  </ol>
</section>

<section id="intro" class="chapter">
  <div class="page">
    <h1>Introdução — Como usar este livro</h1>
    <div class="chapter-meta">Leitura prática • Exercícios diários • Ética</div>
    <p>Este livro foi construído para desenvolver três pilares fundamentais: <strong>inteligência emocional</strong>, <strong>conversação de alto nível</strong> e <strong>presença autêntica</strong>.</p>
    <p>Leia um capítulo por vez e aplique os exercícios no mesmo dia. Nada aqui depende de manipulação; a proposta é comunicação madura, respeito e clareza.</p>
    <h2>Princípios do método</h2>
    <ul class="checklist">
      <li><strong>Respeito e consentimento:</strong> sem insistência quando não há abertura.</li>
      <li><strong>Autenticidade:</strong> melhorar sua comunicação real, sem "virar personagem".</li>
      <li><strong>Clareza emocional:</strong> leveza com responsabilidade.</li>
      <li><strong>Contexto profissional:</strong> discrição e maturidade sempre.</li>
    </ul>
    <h2>Estrutura dos capítulos</h2>
    <p>Cada capítulo contém: <em>visão geral</em>, <em>ideias-chave</em>, <em>aplicação prática</em>, <em>exercícios</em>, <em>frases úteis</em>, <em>checklist</em> e <em>reflexão</em>. Use o checklist ao final de cada interação importante.</p>
    <p>O objetivo não é impressionar, mas desenvolver habilidades reais de conexão humana baseadas em respeito, autenticidade e presença.</p>
  </div>
</section>

{''.join(chapters_html)}

<section id="conclusao" class="chapter">
  <div class="page">
    <h1>Notas do Leitor</h1>
    <div class="chapter-meta">Reflexão final • Aplicação prática • Crescimento contínuo</div>
    <p>Você chegou ao final desta jornada. Parabéns por ter dedicado tempo e energia para desenvolver suas habilidades de conexão humana.</p>
    <h2>O que você aprendeu</h2>
    <p>Ao longo destas páginas, você explorou os fundamentos da conexão autêntica: presença, autenticidade, respeito, reciprocidade e comunicação madura. Esses princípios não são técnicas temporárias, mas fundamentos duradouros que você pode aplicar pelo resto da vida.</p>
    <h2>Próximos passos</h2>
    <ul class="checklist">
      <li><strong>Revise regularmente:</strong> volte aos capítulos que mais ressoaram com você. A releitura traz novos insights.</li>
      <li><strong>Pratique consistentemente:</strong> os exercícios só funcionam se você praticar. Escolha 2-3 exercícios por semana e aplique.</li>
      <li><strong>Mantenha um diário:</strong> anote suas interações, o que funcionou, o que não funcionou. Autoconsciência é a chave do crescimento.</li>
      <li><strong>Seja paciente:</strong> conexões profundas levam tempo. Não espere resultados imediatos. Confie no processo.</li>
    </ul>
    <h2>Lembre-se</h2>
    <p>O objetivo não é impressionar ou conquistar, mas <strong>conectar de forma autêntica e respeitosa</strong>. Quando você pratica presença, autenticidade e respeito, a conexão acontece naturalmente.</p>
    <p>Mantenha seus valores. Não abandone quem você é para agradar outra pessoa. Autenticidade atrai autenticidade.</p>
    <h2>Espaço para suas notas</h2>
    <p style="min-height: 8cm; border: 1px dashed #d4af37; padding: 10px; background-color: #fff9e6;">
      <em>Use este espaço para anotar suas reflexões, aprendizados e próximos passos...</em>
    </p>
    <hr class="sep" />
    <p style="text-align: center; color: #7f8c8d; font-style: italic; margin-top: 20px;">
      "A conexão mais profunda acontece quando você para de tentar impressionar e começa a ser genuinamente você."<br/>
      <strong>— {escape_html(AUTHOR)}</strong>
    </p>
  </div>
</section>

</body>
</html>
"""
    return html


# =========================
# EXPORTAÇÃO: HTML + PDF
# =========================
def ensure_dir(path: str) -> None:
    """Garante que o diretório existe."""
    os.makedirs(path, exist_ok=True)


def write_file(path: str, content: str) -> None:
    """Escreve conteúdo em arquivo."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def html_to_pdf(html_path: str, pdf_path: str) -> None:
    """Converte HTML para PDF. Tenta WeasyPrint primeiro, depois xhtml2pdf."""
    # Tenta WeasyPrint primeiro (melhor qualidade)
    try:
        from weasyprint import HTML  # type: ignore
        print("[INFO] Usando WeasyPrint para converter HTML para PDF...")
        HTML(filename=html_path).write_pdf(pdf_path)
        return
    except (ImportError, OSError) as e:
        # Se WeasyPrint não funcionar (comum no Windows), usa xhtml2pdf
        print("[INFO] WeasyPrint não disponível, usando xhtml2pdf...")
        try:
            from xhtml2pdf import pisa  # type: ignore
            
            # Lê o HTML
            with open(html_path, "r", encoding="utf-8") as html_file:
                html_content = html_file.read()
            
            # Converte para PDF
            with open(pdf_path, "w+b") as result_file:
                pisa_status = pisa.CreatePDF(
                    html_content,
                    dest=result_file,
                    encoding='utf-8'
                )
            
            if pisa_status.err:
                raise RuntimeError(f"Erro ao gerar PDF: {pisa_status.err}")
            
            print("[INFO] PDF gerado com sucesso usando xhtml2pdf!")
            return
            
        except ImportError:
            raise RuntimeError(
                "Nenhum conversor PDF disponível.\n"
                "Instale um dos seguintes:\n"
                "  pip install xhtml2pdf\n"
                "  (ou pip install weasyprint + bibliotecas GTK+ no Windows)\n"
                f"Erro WeasyPrint: {e}"
            )


def main():
    """Função principal."""
    print(f"[INFO] Gerando livro: {BOOK_TITLE}")
    print(f"[INFO] Autor: {AUTHOR}")
    print(f"[INFO] Total de capítulos: {len(CHAPTERS)}")
    print(f"[INFO] Páginas planejadas: 80 (1 capa + 1 sumário + 1 intro + 77 capítulos)")
    
    ensure_dir(OUTPUT_DIR)

    html = build_html()
    html_path = os.path.join(OUTPUT_DIR, HTML_NAME)
    pdf_path = os.path.join(OUTPUT_DIR, PDF_NAME)

    write_file(html_path, html)
    print(f"[OK] HTML gerado: {html_path}")

    html_to_pdf(html_path, pdf_path)
    print(f"[OK] PDF gerado:  {pdf_path}")

    print("\n[INFO] Livro gerado com sucesso!")
    print(f"[INFO] Abra {pdf_path} para visualizar o resultado.")


if __name__ == "__main__":
    main()
