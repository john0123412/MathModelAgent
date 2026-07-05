function Para(el)
  if #el.content == 1 and el.content[1].t == "Str" and el.content[1].text == "MMA_PDF_PAGEBREAK" then
    return pandoc.RawBlock("latex", "\\clearpage")
  end
end
