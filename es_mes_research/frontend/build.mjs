import {mkdir,copyFile} from 'node:fs/promises';
const target=new URL('../src/es_mes/web/',import.meta.url);
await mkdir(target,{recursive:true});
for(const file of ['app.js','chart.js','style.css']) await copyFile(new URL(file,import.meta.url),new URL(file,target));
await copyFile(new URL('node_modules/vue/dist/vue.runtime.esm-browser.prod.js',import.meta.url),new URL('vue.js',target));
await copyFile(new URL('node_modules/vue/LICENSE',import.meta.url),new URL('vue.LICENSE',target));
