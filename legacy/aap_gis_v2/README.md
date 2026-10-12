# Gerador de Livro PDF

Gera automaticamente um livro elegante em PDF com **exatamente 80 páginas**, incluindo capa, sumário, introdução e 16 capítulos.

## Pré-requisitos

- Python 3.10 ou superior
- pip (gerenciador de pacotes Python)

## Instalação

1. Clone ou baixe este projeto
2. Instale as dependências:

```bash
pip install -r requirements.txt
```

**Nota sobre conversão PDF:**
- O script usa `xhtml2pdf` por padrão (funciona em Windows, Linux e Mac sem dependências extras).
- Se preferir usar WeasyPrint (melhor qualidade, mas requer bibliotecas GTK+ no Windows), instale: `pip install weasyprint`

## Execução

Execute o script:

```bash
python gerar_livro.py
```

## Saídas Geradas

O script cria automaticamente a pasta `./saida/` com:

- `livro.html` - HTML completo do livro (pode ser aberto no navegador)
- `livro.pdf` - PDF final com 80 páginas exatas

## Estrutura do Livro

- **Página 1:** Capa elegante (título, subtítulo, autor, data)
- **Página 2:** Sumário com numeração automática de páginas
- **Página 3:** Introdução (como usar o livro)
- **Páginas 4-80:** 16 capítulos
  - Capítulos 1-13: 5 páginas cada
  - Capítulos 14-16: 4 páginas cada

## Características

- ✅ PDF A4 com margens elegantes
- ✅ Cabeçalho com título do livro e capítulo atual
- ✅ Rodapé com numeração de páginas
- ✅ Sumário com links navegáveis e numeração automática
- ✅ Design claro e profissional
- ✅ Fontes DejaVu (serif para títulos, sans para corpo)
- ✅ Exatamente 80 páginas (controlado por estrutura de páginas)

## Personalização

Para alterar o conteúdo, edite as constantes no início de `gerar_livro.py`:

- `BOOK_TITLE` - Título do livro
- `BOOK_SUBTITLE` - Subtítulo
- `AUTHOR` - Nome do autor
- `CHAPTERS` - Lista de títulos dos capítulos

## Troubleshooting

**Erro: "WeasyPrint não está instalado" ou "cannot load library 'libgobject-2.0-0'"**
- Este é um problema comum no Windows. O script agora usa `xhtml2pdf` por padrão, que funciona sem dependências extras.
- Se você quiser usar WeasyPrint (melhor qualidade), precisa instalar as bibliotecas GTK+ no Windows primeiro.

**PDF com número de páginas diferente**
- O script usa estrutura de páginas explícitas. Se houver diferença, pode ser devido às limitações do conversor PDF usado.
- `xhtml2pdf` pode ter pequenas variações no número de páginas dependendo do conteúdo.

**Nota sobre recursos avançados:**
- Cabeçalhos/rodapés automáticos e numeração de páginas no sumário funcionam apenas com WeasyPrint.
- Com `xhtml2pdf`, o PDF será gerado sem esses recursos, mas ainda será legível e bem formatado.
