def classFactory(iface):
    from .aap_plugin import AAPGISPlugin
    return AAPGISPlugin(iface)
