document.querySelectorAll('.availability').forEach((section) => {
  const button = section.querySelector('.add-range');
  button.type = 'button';
  button.addEventListener('click', () => {
    const prefix = section.dataset.prefix;
    const count = section.querySelector(`[name="${prefix}-TOTAL_FORMS"]`);
    const index = Number(count.value);
    if (index >= 50) return;
    const template = section.querySelector('template');
    const range = template.content.cloneNode(true);
    range.querySelectorAll('[name], [id], [for]').forEach((element) => {
      for (const attribute of ['name', 'id', 'for']) {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll('__prefix__', index));
        }
      }
    });
    section.querySelector('.ranges').appendChild(range);
    count.value = index + 1;
    section.querySelector('.range:last-child input').focus();
    button.disabled = Number(count.value) >= 50;
  });
});
