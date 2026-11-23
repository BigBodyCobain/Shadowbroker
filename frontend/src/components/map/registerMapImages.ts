import { getAllPinIcons } from '@/components/map/pinIcons';
import {
  svgPlaneCyan, svgPlaneYellow, svgPlaneOrange, svgPlanePurple, svgFighter, svgHeli, svgHeliCyan, svgHeliDimCyan, svgHeliOrange, svgHeliPurple, svgHeliSlate, svgHeliAmber, svgTanker, svgRecon,
  svgPlanePink, svgPlaneAlertRed, svgPlaneDarkBlue, svgPlaneWhiteAlert, svgHeliPink, svgHeliAlertRed, svgHeliDarkBlue, svgHeliBlue, svgHeliLime, svgHeliWhiteAlert, svgPlaneBlack, svgHeliBlack, svgDrone,
  svgDataCenter, svgPowerPlant, svgRadioTower, svgShipGray, svgShipRed, svgShipYellow, svgShipBlue, svgShipWhite, svgShipPink, svgShipGreyBlue, svgShipAmber, svgCarrier, svgCctv, svgSatDish, svgLoRaSat, svgScannerTower, svgWarning, svgThreat,
  svgTriangleYellow, svgTriangleRed, svgTrianglePink, svgTriangleGreen,
  svgFireYellow, svgFireOrange, svgFireRed, svgFireDarkRed, svgFireClusterSmall, svgFireClusterMed, svgFireClusterLarge, svgFireClusterXL,
  svgPotusPlane, svgPotusHeli,
  svgAirlinerCyan, svgAirlinerDimCyan, svgAirlinerOrange, svgAirlinerPurple, svgAirlinerSlate, svgAirlinerYellow, svgAirlinerAmber, svgAirlinerPink, svgAirlinerRed, svgAirlinerDarkBlue, svgAirlinerBlue, svgAirlinerLime, svgAirlinerBlack, svgAirlinerWhite,
  svgTurbopropCyan, svgTurbopropDimCyan, svgTurbopropOrange, svgTurbopropPurple, svgTurbopropSlate, svgTurbopropYellow, svgTurbopropAmber, svgTurbopropPink, svgTurbopropRed, svgTurbopropDarkBlue, svgTurbopropBlue, svgTurbopropLime, svgTurbopropBlack, svgTurbopropWhite,
  svgBizjetCyan, svgBizjetDimCyan, svgBizjetOrange, svgBizjetPurple, svgBizjetSlate, svgBizjetYellow, svgBizjetAmber, svgBizjetPink, svgBizjetRed, svgBizjetDarkBlue, svgBizjetBlue, svgBizjetLime, svgBizjetBlack, svgBizjetWhite,
  svgAirlinerGrey, svgTurbopropGrey, svgBizjetGrey, svgHeliGrey,
  makeMilBaseSvg, makeMilBaseCircleSvg, MILBASE_ICON_SPECS, makeVolcanoSvg, VOLCANO_ICON_SPECS, WEATHER_ICON_SPECS, CT_ICON_SPECS,
} from '@/components/map/icons/AircraftIcons';
import { makeSatSvg, makeISSSvg, makeTrainSvg } from '@/components/map/icons/SatelliteIcons';
import { makeUfoSvg, makeUfoClusterSvg, makeWaterDropSvg, makeWaterDropClusterSvg } from '@/components/map/icons/OverlayIcons';

export function registerMapImages(loadImg: (id: string, url: string) => void) {
    // AI Intel teardrop pin icons — one per category color
    for (const [id, url] of getAllPinIcons()) {
      loadImg(id, url);
    }

    // Critical icons — needed immediately for default-on layers
    loadImg('svgPlaneCyan', svgPlaneCyan);
    loadImg('svgPlaneYellow', svgPlaneYellow);
    loadImg('svgPlaneOrange', svgPlaneOrange);
    loadImg('svgPlanePurple', svgPlanePurple);
    loadImg('svgHeli', svgHeli);
    loadImg('svgHeliCyan', svgHeliCyan);
    loadImg('svgHeliDimCyan', svgHeliDimCyan);
    loadImg('svgHeliOrange', svgHeliOrange);
    loadImg('svgHeliPurple', svgHeliPurple);
    loadImg('svgHeliSlate', svgHeliSlate);
    loadImg('svgHeliAmber', svgHeliAmber);
    loadImg('svgHeliBlue', svgHeliBlue);
    loadImg('svgHeliLime', svgHeliLime);
    loadImg('svgFighter', svgFighter);
    loadImg('svgTanker', svgTanker);
    loadImg('svgRecon', svgRecon);
    loadImg('svgAirlinerCyan', svgAirlinerCyan);
    loadImg('svgAirlinerDimCyan', svgAirlinerDimCyan);
    loadImg('svgAirlinerOrange', svgAirlinerOrange);
    loadImg('svgAirlinerPurple', svgAirlinerPurple);
    loadImg('svgAirlinerSlate', svgAirlinerSlate);
    loadImg('svgAirlinerYellow', svgAirlinerYellow);
    loadImg('svgAirlinerAmber', svgAirlinerAmber);
    loadImg('svgTurbopropCyan', svgTurbopropCyan);
    loadImg('svgTurbopropDimCyan', svgTurbopropDimCyan);
    loadImg('svgTurbopropOrange', svgTurbopropOrange);
    loadImg('svgTurbopropPurple', svgTurbopropPurple);
    loadImg('svgTurbopropSlate', svgTurbopropSlate);
    loadImg('svgTurbopropYellow', svgTurbopropYellow);
    loadImg('svgTurbopropAmber', svgTurbopropAmber);
    loadImg('svgBizjetCyan', svgBizjetCyan);
    loadImg('svgBizjetDimCyan', svgBizjetDimCyan);
    loadImg('svgBizjetOrange', svgBizjetOrange);
    loadImg('svgBizjetPurple', svgBizjetPurple);
    loadImg('svgBizjetSlate', svgBizjetSlate);
    loadImg('svgBizjetYellow', svgBizjetYellow);
    loadImg('svgBizjetAmber', svgBizjetAmber);
    loadImg('svgAirlinerGrey', svgAirlinerGrey);
    loadImg('svgTurbopropGrey', svgTurbopropGrey);
    loadImg('svgBizjetGrey', svgBizjetGrey);
    loadImg('svgHeliGrey', svgHeliGrey);
    loadImg('svgShipGray', svgShipGray);
    loadImg('svgShipRed', svgShipRed);
    loadImg('svgShipYellow', svgShipYellow);
    loadImg('svgShipBlue', svgShipBlue);
    loadImg('svgShipWhite', svgShipWhite);
    loadImg('svgShipPink', svgShipPink);
    loadImg('svgShipGreyBlue', svgShipGreyBlue);
    loadImg('svgShipAmber', svgShipAmber);
    loadImg('svgCarrier', svgCarrier);
    loadImg('svgWarning', svgWarning);
    loadImg('icon-threat', svgThreat);

    // Deferred icons — for off-by-default layers and rare variants
    // Loaded in next frame to avoid blocking initial map render
    setTimeout(() => {
      loadImg('svgRadioTower', svgRadioTower);
      loadImg('svgSatDish', svgSatDish);
      loadImg('svgLoRaSat', svgLoRaSat);
      loadImg('svgScannerTower', svgScannerTower);
      loadImg('svgPlanePink', svgPlanePink);
      loadImg('svgPlaneAlertRed', svgPlaneAlertRed);
      loadImg('svgPlaneDarkBlue', svgPlaneDarkBlue);
      loadImg('svgPlaneWhiteAlert', svgPlaneWhiteAlert);
      loadImg('svgPlaneBlack', svgPlaneBlack);
      loadImg('svgHeliPink', svgHeliPink);
      loadImg('svgHeliAlertRed', svgHeliAlertRed);
      loadImg('svgHeliDarkBlue', svgHeliDarkBlue);
      loadImg('svgHeliWhiteAlert', svgHeliWhiteAlert);
      loadImg('svgHeliBlack', svgHeliBlack);
      loadImg('svgPotusPlane', svgPotusPlane);
      loadImg('svgPotusHeli', svgPotusHeli);
      loadImg('svgAirlinerPink', svgAirlinerPink);
      loadImg('svgAirlinerRed', svgAirlinerRed);
      loadImg('svgAirlinerDarkBlue', svgAirlinerDarkBlue);
      loadImg('svgAirlinerBlue', svgAirlinerBlue);
      loadImg('svgAirlinerLime', svgAirlinerLime);
      loadImg('svgAirlinerBlack', svgAirlinerBlack);
      loadImg('svgAirlinerWhite', svgAirlinerWhite);
      loadImg('svgTurbopropPink', svgTurbopropPink);
      loadImg('svgTurbopropRed', svgTurbopropRed);
      loadImg('svgTurbopropDarkBlue', svgTurbopropDarkBlue);
      loadImg('svgTurbopropBlue', svgTurbopropBlue);
      loadImg('svgTurbopropLime', svgTurbopropLime);
      loadImg('svgTurbopropBlack', svgTurbopropBlack);
      loadImg('svgTurbopropWhite', svgTurbopropWhite);
      loadImg('svgBizjetPink', svgBizjetPink);
      loadImg('svgBizjetRed', svgBizjetRed);
      loadImg('svgBizjetDarkBlue', svgBizjetDarkBlue);
      loadImg('svgBizjetBlue', svgBizjetBlue);
      loadImg('svgBizjetLime', svgBizjetLime);
      loadImg('svgBizjetBlack', svgBizjetBlack);
      loadImg('svgBizjetWhite', svgBizjetWhite);
      loadImg('svgDrone', svgDrone);
      loadImg('svgCctv', svgCctv);
      loadImg('icon-liveua-yellow', svgTriangleYellow);
      loadImg('icon-liveua-red', svgTriangleRed);
      loadImg('icon-aprs-triangle', svgTrianglePink);
      loadImg('icon-mesh-triangle', svgTriangleGreen);
      // FIRMS fire icons
      loadImg('fire-yellow', svgFireYellow);
      loadImg('fire-orange', svgFireOrange);
      loadImg('fire-red', svgFireRed);
      loadImg('fire-darkred', svgFireDarkRed);
      loadImg('fire-cluster-sm', svgFireClusterSmall);
      loadImg('fire-cluster-md', svgFireClusterMed);
      loadImg('fire-cluster-lg', svgFireClusterLarge);
      loadImg('fire-cluster-xl', svgFireClusterXL);
      // Data center icon
      loadImg('datacenter', svgDataCenter);
      // Power plant icon
      loadImg('power-plant', svgPowerPlant);
      // Satellite mission-type icons
      loadImg('sat-mil', makeSatSvg('#ff3333'));
      loadImg('sat-sar', makeSatSvg('#00e5ff'));
      loadImg('sat-sigint', makeSatSvg('#ffffff'));
      loadImg('sat-nav', makeSatSvg('#4488ff'));
      loadImg('sat-ew', makeSatSvg('#ff00ff'));
      loadImg('sat-com', makeSatSvg('#44ff44'));
      loadImg('sat-station', makeSatSvg('#ffdd00'));
      loadImg('sat-gen', makeSatSvg('#aaaaaa'));
      // ISS special icon (larger, with built-in halo ring)
      loadImg('sat-iss', makeISSSvg());
      // Train icons
      loadImg('train-amtrak', makeTrainSvg('#ffffff'));
      loadImg('train-fin', makeTrainSvg('#ffffff'));
      // Military base icons (square with X or circle)
      for (const spec of MILBASE_ICON_SPECS) {
        loadImg(
          spec.id,
          spec.svg ?? (spec.shape === 'circle'
            ? makeMilBaseCircleSvg(spec.fill, spec.inner)
            : makeMilBaseSvg(spec.fill, spec.inner)),
        );
      }
      // Volcano icons (triangle cone)
      for (const spec of VOLCANO_ICON_SPECS) {
        loadImg(spec.id, makeVolcanoSvg(spec.fill));
      }
      // Weather alert icons
      for (const spec of WEATHER_ICON_SPECS) {
        loadImg(spec.id, spec.svg);
      }
      // CrowdThreat category icons
      for (const spec of CT_ICON_SPECS) {
        loadImg(spec.id, spec.svg);
      }
      // UAP (UFO) icons — individual + cluster
      loadImg('ufo-icon', makeUfoSvg());
      loadImg('ufo-cluster', makeUfoClusterSvg());
      // Wastewater water drop icons — individual + cluster
      loadImg('ww-clean', makeWaterDropSvg('#00e5ff'));
      loadImg('ww-alert', makeWaterDropSvg('#ff2222', '#ff4444'));
      loadImg('ww-stale', makeWaterDropSvg('#556677'));
      loadImg('ww-cluster', makeWaterDropClusterSvg('#00e5ff'));
    }, 0);
}
