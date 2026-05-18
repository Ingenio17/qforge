Live Interactive
===========================

Want to try qforge interactive mode without installing anything locally? Below is a fully functional sandbox running directly in your browser. Powered by MyBinder, this secure terminal workspace comes pre-installed with ``qforge`` and its heavy numerical simulation backends (``QuTiP``, ``scqubits``).

.. note::
   **🚀 Time Notice**
   
   Because this environment provisions dedicated compute resources in the cloud, launching the terminal may take a short moment. Please do not close or refresh the page while the spinner is loading!

How to Use the Sandbox
----------------------

1. **Wait for Launch:** Once the Binder loading phase completes, a full-screen command terminal will appear and automatically boot straight into the ``qforge --interactive`` wizard.
2. **Interact with the Wizard:** Follow the guided terminal menus. You can type numeric selections (e.g., ``1``) or use word strings (e.g., ``create a qubit``) to explore hardware configuration, pulse calibrations, and OpenQASM transpilation workflows.
3. **Autocompletion:** Take advantage of built-in command tab-completion! Press the ``Tab`` key while typing qubit names or coupling choices to see valid configurations.
4. **Escaping/Quitting:** To cleanly exit a wizard workflow or shut down the interactive terminal interface at any point, type ``exit``, ``quit``, or hit ``Ctrl+C``.

Live Interactive
----------------

.. raw:: html

   <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; border: 1px solid #2b2b2b; border-radius: 8px; margin: 20px 0; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
       <iframe src="https://mybinder.org/v2/gh/Ingenio17/qforge/master?urlpath=terminals/1" 
               style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0; background: #1a1a1a;" 
               allowfullscreen>
       </iframe>
   </div>