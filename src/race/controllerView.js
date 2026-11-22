export function controllerView(controller,manualView='dashboard',{wall=false,dataMode}={}){
 if(wall && controller?.mode==='MANUAL')return dataMode==='LIVE' && controller.manualPresentation==='live'?'live':'dashboard';
 return controller?.mode==='AUTO' ? (controller.view==='live'?'live':'dashboard') : manualView;
}

// Routes control tool visibility, never backend authority or telemetry subscriptions.
export function viewAccess(pathname,search='') {
 const wall=pathname==='/wall'||new URLSearchParams(search).get('wall')==='1';
 return {wall,developer:!wall&&pathname==='/dev'};
}
