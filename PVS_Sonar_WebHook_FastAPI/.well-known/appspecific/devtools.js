document.getElementById('scan-button').addEventListener('click', () => {
  chrome.devtools.inspectedWindow.eval(
    'console.log("Scanning project for PVS+Sonar integration")',
    function(result, isException) {
      if (isException) {
        console.error('Exception occurred:', isException);
      } else {
        console.log('Scan completed:', result);
      }
    }
  );
});