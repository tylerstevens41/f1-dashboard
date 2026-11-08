export function controllerView(controller,manualView='dashboard'){
 return controller?.mode==='AUTO' ? (controller.view==='live'?'live':'dashboard') : manualView;
}
