// Serves the Maestro interface below a path prefix such as /spark-4d3f/maestro/.
//
// The React interface of Maestro addresses its server with root-absolute URLs
// (`/api/v1/...`, `/maestro-icon.png`), and so do the file addresses the server
// returns. Behind a reverse proxy that routes a prefix to Maestro and strips it,
// every such URL reaches the root of the proxy instead of Maestro. The image
// loads this script first in index.html; it takes the prefix from the address
// the page was loaded from and puts it in front of every root-absolute URL the
// page requests through the ways the interface addresses its server: fetch, the
// service worker, window.open and the src and href of every element. Served at
// the root, the prefix is empty and the script changes nothing.
(function () {
  'use strict'
  var base = new URL('.', document.baseURI).pathname.replace(/\/+$/, '')
  if (!base) return
  var prefix = base + '/'

  // A root-absolute path gets the prefix; a relative, protocol-relative, foreign
  // or already prefixed URL stays as it is.
  function rebase(value) {
    if (typeof value !== 'string') {
      if (value instanceof URL) {
        if (value.origin !== location.origin) return value
        var copy = new URL(value.href)
        copy.pathname = rebase(copy.pathname)
        return copy
      }
      return value
    }
    if (value.charAt(0) !== '/' || value.charAt(1) === '/') {
      if (value.indexOf(location.origin + '/') !== 0) return value
      return location.origin + rebase(value.slice(location.origin.length))
    }
    if (value === base || value.indexOf(prefix) === 0) return value
    return base + value
  }
  window.__maestroRebase = rebase

  var nativeFetch = window.fetch
  window.fetch = function (input, init) {
    if (input instanceof Request) {
      var target = rebase(input.url)
      if (target !== input.url) input = new Request(target, input)
      return nativeFetch.call(this, input, init)
    }
    return nativeFetch.call(this, rebase(input), init)
  }

  var nativeWindowOpen = window.open
  window.open = function (url) {
    var args = Array.prototype.slice.call(arguments)
    args[0] = rebase(url)
    return nativeWindowOpen.apply(this, args)
  }

  if (navigator.serviceWorker && navigator.serviceWorker.register) {
    var container = navigator.serviceWorker
    var nativeRegister = container.register
    container.register = function (url, options) {
      var rebasedOptions = options ? Object.assign({}, options) : undefined
      if (rebasedOptions && rebasedOptions.scope) rebasedOptions.scope = rebase(rebasedOptions.scope)
      return nativeRegister.call(container, rebase(url), rebasedOptions)
    }
  }

  // Element URLs: React writes src and href through setAttribute or through the
  // property, so both paths carry the prefix.
  var URL_ATTRIBUTES = { src: true, href: true, poster: true, action: true, formaction: true }
  var nativeSetAttribute = Element.prototype.setAttribute
  Element.prototype.setAttribute = function (name, value) {
    if (URL_ATTRIBUTES[String(name).toLowerCase()] && typeof value === 'string') value = rebase(value)
    return nativeSetAttribute.call(this, name, value)
  }
  var ELEMENT_PROPERTIES = [
    ['HTMLImageElement', 'src'], ['HTMLMediaElement', 'src'], ['HTMLSourceElement', 'src'],
    ['HTMLScriptElement', 'src'], ['HTMLIFrameElement', 'src'], ['HTMLTrackElement', 'src'],
    ['HTMLEmbedElement', 'src'], ['HTMLInputElement', 'src'], ['HTMLVideoElement', 'poster'],
    ['HTMLAnchorElement', 'href'], ['HTMLAreaElement', 'href'], ['HTMLLinkElement', 'href'],
    ['HTMLBaseElement', 'href'], ['HTMLFormElement', 'action'],
  ]
  ELEMENT_PROPERTIES.forEach(function (entry) {
    var Type = window[entry[0]]
    if (!Type) return
    var descriptor = Object.getOwnPropertyDescriptor(Type.prototype, entry[1])
    if (!descriptor || !descriptor.set) return
    Object.defineProperty(Type.prototype, entry[1], {
      configurable: true,
      enumerable: descriptor.enumerable,
      get: descriptor.get,
      set: function (value) { descriptor.set.call(this, typeof value === 'string' ? rebase(value) : value) },
    })
  })

  // The elements the parser created from index.html itself.
  function rebaseDocument() {
    var elements = document.querySelectorAll('[src],[href],[poster]')
    for (var i = 0; i < elements.length; i++) {
      ['src', 'href', 'poster'].forEach(function (name) {
        var value = elements[i].getAttribute(name)
        if (value !== null && rebase(value) !== value) nativeSetAttribute.call(elements[i], name, rebase(value))
      })
    }
  }
  rebaseDocument()
  document.addEventListener('DOMContentLoaded', rebaseDocument)
})()
