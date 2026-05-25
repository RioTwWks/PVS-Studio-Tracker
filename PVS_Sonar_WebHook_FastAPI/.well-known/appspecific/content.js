console.log('PVS+Sonar content script loaded');

// Пример: добавляем кнопку DevTools в страницу
if (window.self === window.top) {
  const devToolsButton = document.createElement('button');
  devToolsButton.textContent = 'PVS+Sonar Tools';
  devToolsButton.style.position = 'fixed';
  devToolsButton.style.top = '10px';
  devToolsButton.style.right = '10px';
  devToolsButton.style.zIndex = '1000';
  devToolsButton.addEventListener('click', () => {
    alert('PVS+Sonar DevTools would open here');
  });
  document.body.appendChild(devToolsButton);
}