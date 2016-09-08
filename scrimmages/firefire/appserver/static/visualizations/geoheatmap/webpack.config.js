var webpack = require('webpack');
var path = require('path');

module.exports = {
    entry: 'visualization_source',
    resolve: {
        root: [
            path.join(__dirname, 'src'),
        ]
    },
    output: {
        filename: 'visualization.js',
        libraryTarget: 'amd'
    },
    module: {
        loaders: [
            {
                test: /leaflet\.heat\.js$/,
                loader: 'imports-loader?L=leaflet'
            }
        ]
    },
    externals: [
        'vizapi/SplunkVisualizationBase',
        'vizapi/SplunkVisualizationUtils'
    ]
};
